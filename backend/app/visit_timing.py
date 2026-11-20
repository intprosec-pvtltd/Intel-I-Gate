"""Resolve visit timing from either saved entry or linked exit evidence."""
from sqlalchemy import select
from .models import Event,Visit,ExitObservation


def visit_timing(db,event):
    visit=db.scalar(select(Visit).where(Visit.event_id==event.id))
    observation=None
    if visit is None:
        observation=db.scalar(select(ExitObservation).where(ExitObservation.track_ref==event.track_ref,ExitObservation.visit_id.is_not(None),ExitObservation.state.in_(['AUTO_CONFIRMED','GUARD_CONFIRMED'])))
        if observation:visit=db.get(Visit,observation.visit_id)
    if visit is None:return None
    entry=db.get(Event,visit.event_id)
    if entry is None:return None
    if observation is None:
        observation=db.scalar(select(ExitObservation).where(ExitObservation.visit_id==visit.id,ExitObservation.state.in_(['AUTO_CONFIRMED','GUARD_CONFIRMED'])).order_by(ExitObservation.created_at.desc()))
    departure=db.scalar(select(Event).where(Event.track_ref==observation.track_ref)) if observation else None
    details=(entry.evidence or {}).get('exit_completion') or {}
    exit_seconds=(observation.evidence or {}).get('video_seconds') if observation else None
    if exit_seconds is None and departure:exit_seconds=departure.frame_seconds
    return {'visit_id':visit.id,'flat':visit.flat,'status':visit.status,'test_mode':visit.historical,
            'entry_at':None if visit.historical else visit.entry_at,'exit_at':None if visit.historical else visit.exit_at,
            'entry_video_seconds':entry.frame_seconds if visit.historical else None,
            'exit_video_seconds':exit_seconds if visit.historical else None,
            'expected_exit_at':visit.expected_exit_at,'saved_at':visit.created_at,'exit_method':details.get('method'),
            'entry_snapshot_id':entry.snapshot_id,'exit_snapshot_id':departure.snapshot_id if departure else None}
