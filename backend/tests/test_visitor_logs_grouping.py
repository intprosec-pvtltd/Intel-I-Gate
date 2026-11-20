from datetime import timedelta
from sqlalchemy import select,func
from app.models import Event,Visit,ExitObservation,Audit,User,now
from tests.test_dedicated_exit import dedicated
from tests.test_auto_exit import sample
from tests.test_auto_test_exit import records,samples


def completed_live(env):
 c,vector,vid,eid,exitid,camera=dedicated(env)
 with env[1]() as db:
  for i in range(3):sample(db,exitid,vector,c,i)
  db.get(Event,eid).verification={'visitor_name':'Test Visitor','visit_purpose':'Relation'};db.commit()
 return vid,eid,exitid,camera


def test_one_row_with_both_observations_in_timeline(client,env):
 vid,eid,exitid,camera=completed_live(env)
 data=client.get('/api/visitor-logs').json()
 assert data['total']==1 and len(data['items'])==1
 row=data['items'][0];assert row['id']==eid and row['visit_id']==vid and row['state']=='COMPLETED'
 assert row['exit_camera_name']=='Exit' and row['visit_timing']['entry_at'] and row['visit_timing']['exit_at']
 timeline=client.get('/api/visitor-logs/'+eid).json()
 assert {x['event_id'] for x in timeline['observations']}=={eid,exitid}
 assert {'Entry','Exit'}=={x['role'] for x in timeline['observations']}
 assert any(x['action']=='EXIT_OBSERVED' for x in timeline['timeline'])
 assert any(x['action']=='AUTO_COMPLETE_EXIT' for x in timeline['timeline'])
 assert {x['event_id'] for x in client.get('/api/visitor-logs/'+exitid).json()['observations']}=={eid,exitid}
 with env[1]() as db:assert db.scalar(select(func.count()).select_from(Event))==2
 assert client.get('/api/events/'+exitid).status_code==200


def test_search_status_purpose_and_exit_camera_filters_return_canonical_row(client,env):
 vid,eid,exitid,camera=completed_live(env)
 for suffix in ('?q=Test%20Visitor','?purpose=Relation','?status=COMPLETED','?status=EXIT_CONFIRMED','?camera_id='+camera):
  data=client.get('/api/visitor-logs'+suffix).json();assert data['total']==1 and data['items'][0]['id']==eid
 assert client.get('/api/visitor-logs?source=test').json()['total']==0


def test_upload_test_pair_groups_without_inventing_timestamps(client,env):
 c,vector,vid,eid,exitid,video=records(env)
 with env[1]() as db:assert samples(db,exitid,vector,c)[-1];db.commit()
 data=client.get('/api/visitor-logs?source=test').json();assert data['total']==1
 assert data['items'][0]['id']==eid
 assert data['items'][0]['visit_timing']['exit_at'] is None
 assert data['items'][0]['visit_timing']['exit_video_seconds']==1.2
 assert len(client.get('/api/visitor-logs/'+eid).json()['observations'])==2


def test_only_saved_visits_are_listed_and_unmatched_exit_is_hidden(client,env):
 c,vector,vid,eid,exitid,video=records(env)
 data=client.get('/api/visitor-logs').json()
 assert data['total']==1 and {r['id'] for r in data['items']}=={eid}


def test_shared_entry_exit_event_remains_visible(client,env):
 c,vector,vid,eid,exitid,video=records(env)
 with env[1]() as db:
  visit=db.get(Visit,vid);visit.status='COMPLETED';db.get(Event,eid).state='COMPLETED'
  db.add(ExitObservation(video_id=video,track_ref=db.get(Event,eid).track_ref,visit_id=vid,state='AUTO_CONFIRMED',evidence={}));db.commit()
 assert eid in {r['id'] for r in client.get('/api/visitor-logs').json()['items']}


def test_grouping_happens_before_count_and_pagination_and_preserves_distinct_visits(client,env):
 with env[1]() as db:
  guard=db.scalar(select(User).where(User.username=='admin'))
  for i in range(51):
   entry=Event(track_ref=f'entry-{i}',state='COMPLETED',verification={'visitor_name':'Same name','visit_purpose':'Delivery'});departure=Event(track_ref=f'exit-{i}',state='EXIT_CONFIRMED');db.add_all([entry,departure]);db.flush()
   visit=Visit(event_id=entry.id,guard_id=guard.id,resident_name='Same resident',flat='B-203',status='COMPLETED',entry_at=now()-timedelta(hours=1),exit_at=now(),completed_at=now());db.add(visit);db.flush()
   db.add(ExitObservation(track_ref=departure.track_ref,visit_id=visit.id,state='AUTO_CONFIRMED',evidence={}))
  db.commit()
 page1=client.get('/api/visitor-logs').json();page2=client.get('/api/visitor-logs?offset=50').json()
 assert page1['total']==page2['total']==51 and len(page1['items'])==50 and len(page2['items'])==1
 ids=[r['visit_id'] for r in page1['items']+page2['items']];assert len(set(ids))==51
 with env[1]() as db:assert db.scalar(select(func.count()).select_from(Event))==102


def test_unverified_events_are_excluded_before_pagination(client,env):
 with env[1]() as db:
  for i,state in enumerate(('PENDING_VERIFICATION','CONFIRMED','EXIT_REVIEW','EXIT_CONFIRMED','CANCELLED','NOT_DELIVERY')):
   db.add(Event(track_ref=f'unsaved-{i}',state=state,verification={}))
  db.commit()
 assert client.get('/api/visitor-logs').json()=={'total':0,'items':[]}
 for status in ('PENDING_VERIFICATION','CONFIRMED','EXIT_REVIEW','CANCELLED'):
  assert client.get('/api/visitor-logs?status='+status).json()['total']==0
 with env[1]() as db:assert db.scalar(select(func.count()).select_from(Event))==6
