from sqlalchemy import select
from app.models import Event
from app.api import event_json
from app.auto_exit import observe
from tests.test_auto_exit import fixture_records,sample
from tests.test_auto_test_exit import records,samples


def test_live_exit_event_exposes_linked_entry_and_crossing_times(env):
    c,vector,visit_id,entry_id,source_id,camera_id=fixture_records(env)
    with env[1]() as db:
        for i in range(3):sample(db,source_id,vector,c,i,crossed=i==1)
        db.commit()
        timing=event_json(db.get(Event,source_id),db)['visit_timing']
        assert timing['visit_id']==visit_id and timing['entry_at'] and timing['exit_at']
        assert timing['exit_at']>timing['entry_at']
        assert not timing['test_mode'] and timing['entry_video_seconds'] is None
        assert event_json(db.get(Event,entry_id),db)['visit_timing']==timing


def test_test_event_exposes_video_offsets_without_calendar_exit_times(env):
    c,vector,visit_id,entry_id,source_id,video_id=records(env)
    with env[1]() as db:
        db.get(Event,entry_id).frame_seconds=2.5
        assert samples(db,source_id,vector,c)[-1];db.commit()
        timing=event_json(db.get(Event,source_id),db)['visit_timing']
        assert timing['test_mode'] and timing['entry_at'] is None and timing['exit_at'] is None
        assert timing['entry_video_seconds']==2.5 and timing['exit_video_seconds']==1.2
        assert timing['exit_method']=='AUTO_TEST_FACE_EXIT'


def test_unlinked_exit_does_not_show_unrelated_visit_times(env):
    c,vector,visit_id,entry_id,source_id,video_id=records(env)
    with env[1]() as db:assert event_json(db.get(Event,source_id),db)['visit_timing'] is None
