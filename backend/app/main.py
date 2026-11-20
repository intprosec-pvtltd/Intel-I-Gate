import asyncio,logging
from collections import defaultdict,deque
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request,HTTPException,WebSocket,WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError,SQLAlchemyError
from .config import Settings
from .database import database
from .storage import Storage
from .worker import Manager
from .security import authenticate
from .models import Camera,Event
from .api import router,camera_json,event_json
from .retention import cleanup
from .visit_sessions import tick
from .accounts import router as accounts_router
from .logs_api import router as logs_router
from .resident_faces import router as resident_faces_router
from .realtime import router as realtime_router, PreviewPeers

class BodyLimit:
    def __init__(self,app,limit):self.app,self.limit=app,limit
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        limit=2048 if scope.get('path')=='/api/resident-response' else self.limit
        try:declared=int(dict(scope['headers']).get(b'content-length',b'0'))
        except ValueError:declared=limit+1
        if declared>limit:return await JSONResponse({'detail':'Request too large'},413)(scope,receive,send)
        used=0
        async def limited():
            nonlocal used
            m=await receive();used+=len(m.get('body',b''))
            if used>limit:raise HTTPException(413,'Request too large')
            return m
        await self.app(scope,limited,send)

def create_app(config=None,sessions=None,start_worker=True):
    c=config or Settings();engine=None
    if sessions is None:engine,sessions=database(c.database_url)
    storage=Storage(c.storage_dir);worker=Manager(c,sessions,storage)
    maintenance_stop=asyncio.Event()
    async def sweep():
        import time
        cleanup_at=0
        while not maintenance_stop.is_set():
            try:await asyncio.to_thread(tick,sessions,c)
            except Exception:logging.getLogger('intel').error('Visit session check failed; retry scheduled')
            if time.monotonic()>=cleanup_at:
                try:await asyncio.to_thread(cleanup,sessions,storage,c)
                except Exception:logging.getLogger('intel').error('Retention cleanup failed; retry scheduled')
                cleanup_at=time.monotonic()+300
            try:await asyncio.wait_for(maintenance_stop.wait(),timeout=c.maintenance_interval_seconds)
            except asyncio.TimeoutError:pass
    @asynccontextmanager
    async def lifespan(app):
        if start_worker:worker.start()
        task=asyncio.create_task(sweep()) if start_worker else None
        yield
        if task:
            maintenance_stop.set()
            await task
        await app.state.preview_peers.close()
        if start_worker:await asyncio.to_thread(worker.close)
        if engine:engine.dispose()
    app=FastAPI(title='INTEL-I Mini',version='0.1.0',lifespan=lifespan)
    app.state.config=c;app.state.sessions=sessions;app.state.storage=storage;app.state.worker=worker;app.state.attempts=defaultdict(deque)
    app.add_middleware(BodyLimit,limit=(c.max_upload_mb+2)*1048576)
    app.add_middleware(CORSMiddleware,allow_origins=c.origins,allow_credentials=True,allow_methods=['GET','POST','PUT','DELETE'],allow_headers=['Content-Type','X-Intel-Request'])
    @app.middleware('http')
    async def security(request:Request,call_next):
        if request.method in ('POST','PUT','DELETE','PATCH') and (request.headers.get('origin') not in c.origins+([c.public_app_url.rstrip('/')] if c.public_app_url else []) or request.headers.get('x-intel-request')!='1'):return JSONResponse({'detail':'Origin or request header not allowed'},403)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer';return response
    @app.exception_handler(RequestValidationError)
    async def validation(request,exc):return JSONResponse({'detail':[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()]},422)
    @app.exception_handler(IntegrityError)
    async def conflict(request,exc):return JSONResponse({'detail':'Duplicate record or conflicting change'},409)
    @app.exception_handler(SQLAlchemyError)
    async def db_error(request,exc):return JSONResponse({'detail':'Database unavailable; operation not confirmed'},503)
    @app.exception_handler(OSError)
    async def io_error(request,exc):return JSONResponse({'detail':'Storage or external process unavailable'},503)
    app.state.preview_peers=PreviewPeers(app)
    app.include_router(realtime_router)
    app.include_router(router)
    app.include_router(logs_router)
    app.include_router(accounts_router)
    app.include_router(resident_faces_router)
    @app.websocket('/ws/{channel}')
    async def websocket(ws:WebSocket,channel:str):
        if channel not in ('events','cameras','analysis') or ws.headers.get('origin') not in c.origins:await ws.close(code=1008);return
        try:authenticate(ws.cookies.get('intel_session'),app)
        except HTTPException:await ws.close(code=1008);return
        await ws.accept()
        try:
            while True:
                authenticate(ws.cookies.get('intel_session'),app)
                if channel=='analysis':
                    await ws.send_json({'type':'analysis','items':worker.analysis_state()});await asyncio.sleep(.2);continue
                with sessions() as db:
                    items=[camera_json(x) for x in db.scalars(select(Camera))] if channel=='cameras' else [event_json(x,db) for x in db.scalars(select(Event).order_by(Event.created_at.desc()).limit(50))]
                await ws.send_json(jsonable_encoder({'type':channel,'items':items}));await asyncio.sleep(2)
        except (WebSocketDisconnect,RuntimeError):pass
        except HTTPException:await ws.close(code=1008)
        except SQLAlchemyError:await ws.close(code=1011)
    return app
