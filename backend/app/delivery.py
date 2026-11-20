"""Conservative delivery evidence and a single, bounded background model worker."""
from collections import OrderedDict, deque
import threading
import time
import math

STRONG_LABELS = {'insulated delivery bag', 'food delivery bag', 'delivery backpack', 'courier bag'}


def associate_objects(scores, labels, boxes, people, threshold):
    """A package alone is not delivery evidence. Ambiguous ownership is rejected."""
    output = {int(tid): [] for tid in people}
    for score, label, box in zip(scores, labels, boxes):
        score = float(score)
        label = str(label).strip().lower().rstrip('.')
        b = [float(v) for v in box]
        if len(b) != 4 or not all(math.isfinite(v) for v in b + [score]):
            continue
        if label not in STRONG_LABELS or score < threshold:
            continue
        area = max(0, b[2]-b[0]) * max(0, b[3]-b[1])
        if area <= 0:
            continue
        owners = []
        for tid, p in people.items():
            person_area = max(1, (p[2]-p[0])*(p[3]-p[1]))
            margin = .08*(p[2]-p[0])
            overlap = max(0, min(b[2], p[2]+margin)-max(b[0], p[0]-margin)) * max(0, min(b[3], p[3])-max(b[1], p[1])) / area
            # Large person-sized text boxes are not bag evidence.
            if overlap >= .75 and .015 <= area/person_area <= .65:
                owners.append(int(tid))
        if len(owners) == 1:
            output[owners[0]].append({'label': label, 'confidence': score, 'box': b})
    return output


class EvidenceWindow:
    def __init__(self, count, span, window):
        self.count, self.span, self.window = count, span, window
        self.hits = deque()
        self.last = None

    def observe(self, seconds, objects):
        # Called once per distinct completed model request, never per display frame.
        if self.last is not None and seconds <= self.last:
            return
        self.last = seconds
        while self.hits and seconds-self.hits[0] > self.window:
            self.hits.popleft()
        if objects:
            self.hits.append(seconds)
        else:
            self.hits.clear()

    def possible(self, seconds):
        while self.hits and seconds-self.hits[0] > self.window:
            self.hits.popleft()
        return len(self.hits) >= self.count and self.hits[-1]-self.hits[0] >= self.span


class DeliveryModel:
    def __init__(self, c):
        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
        self.c = c
        path = str(c.model_dir/'grounding_dino_tiny')
        self.processor = AutoProcessor.from_pretrained(path, local_files_only=True)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(path, local_files_only=True).to(c.dino_device).eval()

    def __call__(self, frame, people):
        import torch
        import inspect
        from PIL import Image
        image = Image.fromarray(frame[:, :, ::-1])
        # Do not let a legacy .env prompt re-enable generic parcel/person labels.
        text = '. '.join(sorted(STRONG_LABELS)) + '.'
        inputs = self.processor(images=image, text=text, return_tensors='pt').to(self.c.dino_device)
        with torch.inference_mode():
            raw = self.model(**inputs)
        post = self.processor.post_process_grounded_object_detection
        threshold = 'threshold' if 'threshold' in inspect.signature(post).parameters else 'box_threshold'
        result = post(raw, inputs.input_ids, **{threshold: max(.5, self.c.delivery_threshold)}, text_threshold=.3, target_sizes=[image.size[::-1]])[0]
        labels = result.get('text_labels', result.get('labels', []))
        return associate_objects(result['scores'], labels, result['boxes'], people, max(.5, self.c.delivery_threshold))


class DeliveryWorker:
    """One model, at most one outstanding task/result per source, fair FIFO admission."""
    def __init__(self, c, factory=DeliveryModel):
        self.c, self.factory = c, factory
        self.condition = threading.Condition()
        self.tasks, self.results = OrderedDict(), {}
        self.outstanding = set()
        self.active = None
        self.closed = False
        self.state, self.error, self.last_ms = 'NOT_LOADED', None, None
        self.thread = threading.Thread(target=self.run, daemon=True, name='intel-delivery')
        self.thread.start()

    def submit(self, key, frame, people, seconds):
        with self.condition:
            if self.closed or self.state == 'FAILED' or key in self.outstanding or len(self.outstanding) >= self.c.max_sources:
                return False
            self.outstanding.add(key)
            self.tasks[key] = (frame.copy(), dict(people), seconds, time.monotonic())
            self.condition.notify()
            return True

    def pending(self, key):
        with self.condition:
            return key in self.outstanding

    def take(self, key):
        with self.condition:
            value = self.results.pop(key, None)
            if value is not None:
                self.outstanding.discard(key)
            return value

    def forget(self, key):
        with self.condition:
            self.tasks.pop(key, None)
            self.results.pop(key, None)
            self.outstanding.discard(key)

    def run(self):
        model = None
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.tasks)
                if self.closed:
                    return
                key, task = self.tasks.popitem(last=False)
                self.active = key
            frame, people, seconds, submitted = task
            started = time.monotonic()
            try:
                if model is None:
                    self.state = 'LOADING'
                    model = self.factory(self.c)
                self.state = 'READY'
                objects = model(frame, people)
                self.error = None
                value = (seconds, submitted, objects, None)
            except Exception as exc:
                # Do not expose source URLs, filenames, tensors or credentials.
                self.error = 'Delivery inference failed (' + type(exc).__name__ + ')'
                if model is None:
                    self.state = 'FAILED'
                value = (seconds, submitted, {}, self.error)
            self.last_ms = round((time.monotonic()-started)*1000, 2)
            with self.condition:
                if key in self.outstanding and not self.closed:
                    self.results[key] = value
                self.active = None

    def close(self):
        with self.condition:
            self.closed = True
            self.tasks.clear()
            self.results.clear()
            self.outstanding.clear()
            self.condition.notify_all()
        self.thread.join(timeout=5)
