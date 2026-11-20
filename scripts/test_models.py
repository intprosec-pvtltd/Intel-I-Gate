"""Real model smoke test; never reports delivery PASS before DINO has run."""
from pathlib import Path
import argparse
import json
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from app.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--video')
    parser.add_argument('--frames', type=int, default=30)
    parser.add_argument('--faces-only', action='store_true')
    args = parser.parse_args()
    import numpy as np
    from app.vision import FaceService, Pipeline
    from app.delivery import DeliveryWorker
    c = Settings()
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    faces = FaceService(c)
    faces.detector.setInputSize((960, 540))
    faces.detector.detect(frame)
    if faces.recognizer.feature(np.zeros((112, 112, 3), dtype=np.uint8)).size != 128:
        raise RuntimeError('Unexpected SFace embedding size')
    print('YuNet and SFace: PASS (smoke inference, not accuracy)')
    report = {'face_models':'PASS', 'scope':'Smoke inference; no labeled accuracy measurement'}
    if not args.faces_only:
        pipeline = Pipeline(c)
        try:
            pipeline.process('smoke', frame, 0, {})
            delivery = pipeline.delivery_worker
            if not delivery.submit('delivery-smoke', frame, {}, 0):
                raise RuntimeError('Delivery test could not start')
            deadline = time.monotonic()+300
            result = None
            while result is None and time.monotonic()<deadline:
                result = delivery.take('delivery-smoke')
                time.sleep(.05)
            if result is None or result[3]:
                raise RuntimeError(result[3] if result else 'Delivery model test timed out')
            print('YOLOv8m, ByteTrack and Grounding DINO: PASS (smoke inference, not accuracy)')
            if args.video:
                from app.media import Decoder
                decoder = Decoder(args.video, c, False)
                counts = []
                try:
                    for index in range(max(1, min(args.frames, 10000))):
                        while pipeline.pending_delivery('local-video'):
                            pipeline.poll_delivery('local-video', False)
                            decoder.touch()
                            time.sleep(.02)
                        image = decoder.read()
                        if image is None:
                            break
                        rows = pipeline.process('local-video', image, index/c.inference_fps, {})
                        value = {'frame':index, 'person_tracks':len(rows), 'usable_faces':sum(bool(r['face']) for r in rows), 'possible_deliveries':sum(r['possible'] for r in rows)}
                        counts.append(value)
                        print(json.dumps(value))
                finally:
                    decoder.close()
                report['video_frames'] = counts
            report.update(pipeline.metrics())
        finally:
            pipeline.close()
    output = Path(__file__).resolve().parents[1]/'docs/local-model-test.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print('Report saved:', output)


if __name__ == '__main__':
    main()
