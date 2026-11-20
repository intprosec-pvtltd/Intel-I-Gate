from sqlalchemy import select,func
from app.models import Event,Visit,ExitObservation
from tests.test_auto_exit import sample
from tests.test_dedicated_exit import dedicated
from tests.test_auto_test_exit import records,samples


def test_live_entry_and_confirmed_exit_have_one_overview_card(client,env):
 c,vector,vid,eid,source,camera=dedicated(env)
 with env[1]() as db:
  for i in range(3):sample(db,source,vector,c,i)
  db.commit();before=db.scalar(select(func.count()).select_from(Event))
 data=client.get('/api/dashboard/recent-events').json()
 assert [x['id'] for x in data]==[eid]
 assert data[0]['visit_timing']['entry_at'] and data[0]['visit_timing']['exit_at']
 # Both source observations remain in digital logs; this is presentation grouping only.
 with env[1]() as db:assert db.scalar(select(func.count()).select_from(Event))==before
 assert client.get('/api/events/'+source).status_code==200
 assert client.get('/api/visitor-logs').json()['total']==1
 assert len(client.get('/api/visitor-logs/'+eid).json()['observations'])==2


def test_uploaded_entry_and_exit_group_without_calendar_exit_time(client,env):
 c,vector,vid,eid,source,video=records(env)
 with env[1]() as db:assert samples(db,source,vector,c)[-1];db.commit()
 data=client.get('/api/dashboard/recent-events').json();assert [x['id'] for x in data]==[eid]
 assert data[0]['visit_timing']['test_mode'] and data[0]['visit_timing']['exit_at'] is None
 assert data[0]['visit_timing']['exit_video_seconds']==1.2


def test_unmatched_exit_observation_is_still_visible(client,env):
 c,vector,vid,eid,source,video=records(env)
 assert {x['id'] for x in client.get('/api/dashboard/recent-events').json()}=={eid,source}


def test_shared_entry_exit_event_is_not_hidden(client,env):
 c,vector,vid,eid,source,video=records(env)
 with env[1]() as db:
  entry=db.get(Event,eid);entry.state='COMPLETED';visit=db.get(Visit,vid);visit.status='COMPLETED'
  db.add(ExitObservation(video_id=video,track_ref=entry.track_ref,visit_id=vid,state='AUTO_CONFIRMED',evidence={}))
  db.commit()
 assert eid in {x['id'] for x in client.get('/api/dashboard/recent-events').json()}
