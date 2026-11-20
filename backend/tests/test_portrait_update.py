import importlib.util
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from sqlalchemy import create_engine,text,inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.vision import passport_crop,FaceService

@pytest.mark.parametrize('x,y',[(400,100),(0,0),(880,440),(0,440),(880,0),(400,440),(0,100),(880,100)])
def test_portrait_keeps_original_face_and_source_pixels_at_edges(x,y):
    frame=np.random.default_rng(20).integers(40,210,(540,960,3),dtype=np.uint8)
    crop=passport_crop(frame,[x,y,80,100]);h,w=crop.shape[:2]
    locations=np.argwhere(np.all(frame==crop[0,0],axis=2))
    assert any(np.array_equal(frame[a:a+h,b:b+w],crop) and b<=x and a<=y and b+w>=x+80 and a+h>=y+100 for a,b in locations)
    assert h>100 and w>80

@pytest.mark.parametrize('bounds',[[0,0,0,20],[0,0,20,-1],[float('nan'),0,20,20]])
def test_portrait_rejects_invalid_bounds(bounds):
    with pytest.raises(ValueError):passport_crop(np.zeros((200,200,3),np.uint8),bounds)

@pytest.mark.parametrize('biometric',[False,True])
def test_face_quality_stays_on_tight_crop_and_embedding_uses_source(biometric):
    frame=np.random.default_rng(20).integers(40,210,(540,960,3),dtype=np.uint8)
    face=np.array([400,100,80,100,420,130,460,130,440,150,425,175,455,175,.99],np.float32)
    class Detector:
        def setInputSize(self,size):pass
        def detect(self,image):return None,np.array([face])
    class Recognizer:
        def alignCrop(self,image,detection):assert image is frame;assert np.array_equal(detection,face);return np.ones((112,112,3),np.uint8)
        def feature(self,image):return np.array([[1.,2.,3.]])
    service=FaceService.__new__(FaceService);service.c=SimpleNamespace(face_min_size=40,biometric_enabled=biometric);service.detector=Detector();service.recognizer=Recognizer()
    result=service.candidates(frame,{1:[350,70,550,500]})[1]
    gray=cv2.cvtColor(frame[100:200,400:480],cv2.COLOR_BGR2GRAY)
    assert result['metrics']['sharpness']==float(cv2.Laplacian(gray,cv2.CV_64F).var())
    assert result['metrics']['framing']=='passport_v2'
    decoded=cv2.imdecode(np.frombuffer(result['jpeg'],np.uint8),cv2.IMREAD_COLOR)
    assert decoded.shape[:2]==(240,187)
    assert result['embedding']==([1.,2.,3.] if biometric else None)


def test_migration_preserves_existing_resident_and_login(tmp_path):
    root=Path(__file__).resolve().parents[1]/'migrations/versions'
    def load(name):
        spec=importlib.util.spec_from_file_location(name,root/(name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    first,second=load('0001_initial'),load('0002_resident_otp')
    engine=create_engine('sqlite:///'+str(tmp_path/'migration.db'))
    with engine.begin() as connection:
        context=MigrationContext.configure(connection)
        with Operations.context(context):
            first.upgrade()
            connection.execute(text("INSERT INTO residents(id,created_at,name,flat,active) VALUES ('old-resident','2026-01-01','Existing','A1',1)"))
            connection.execute(text("INSERT INTO users(id,created_at,username,password_hash,role,active,token_version) VALUES ('old-user','2026-01-01','existing-login','unchanged-hash','admin',1,0)"))
            second.upgrade()
            assert connection.execute(text("SELECT phone_encrypted,revision FROM residents WHERE id='old-resident'")).one()==(None,0)
            assert connection.execute(text("SELECT password_hash FROM users WHERE id='old-user'")).scalar_one()=='unchanged-hash'
            assert {'delivery_otps','otp_send_limits'}.issubset(inspect(connection).get_table_names())
            second.downgrade()
            assert connection.execute(text("SELECT name FROM residents WHERE id='old-resident'")).scalar_one()=='Existing'
    engine.dispose()
