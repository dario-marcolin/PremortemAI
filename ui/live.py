"""A live run: the pipeline works in a background thread, so the page can rerun (clicks, the timer)
without cutting the stream. The thread only touches the Run object, never Streamlit.

Stop is honoured between two updates of the graph: an LLM call already sent finishes first.
Resume continues from the last checkpoint (Run.advance with no input).
"""

import threading
from time import perf_counter

from premortem.runner import Run


class LiveRun:
    def __init__(self, run: Run, review: bool = True, evaluate: bool = False, sync: bool = False):
        self.run = run
        self.review = review  # False: the strategy is approved automatically, as in the evaluation
        self.evaluate = evaluate  # score the blueprint when the run ends (two calls to the judge)
        self.sync = sync  # tests: advance in the calling thread
        self.evaluating = False
        self.eval_error: str | None = None
        self._thread: threading.Thread | None = None
        self._stop = False
        self._started: float | None = None
        self.stopped = False

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def stopping(self) -> bool:
        return self._stop and self.busy

    @property
    def status(self) -> str:
        status = self.run.status
        if status == "running" and not self.busy and self.stopped:
            return "stopped"
        return status

    @property
    def elapsed(self) -> float:
        extra = perf_counter() - self._started if self.busy and self._started else 0.0
        return self.run.seconds + extra

    def start(self) -> None:
        if self.busy or self.run.status in ("done", "waiting"):
            return
        self._stop, self.stopped = False, False
        if self.run.status == "failed":
            self.run.error = None  # retry continues from the last finished step
        if self.sync:
            self._work()
            return
        self._thread = threading.Thread(target=self._work, name=f"run-{self.run.run_id}", daemon=True)
        self._started = perf_counter()
        self._thread.start()

    def _work(self) -> None:
        while True:
            for _ in self.run.advance():
                if self._stop:
                    self.stopped = True
                    return
            if self.run.status == "waiting" and not self.review:
                self.run.answer({"approved": True})
                continue
            break
        if self.run.status == "done" and self.evaluate:
            self._evaluate()

    def _evaluate(self) -> None:
        from eval.metrics import evaluate, find_case

        self.evaluating = True
        try:
            case = find_case(self.run.document)
            evaluate(self.run.dir, self.run.document_text, case and case.get("trap"), settings=self.run.settings)
        except Exception as e:  # the blueprint is saved; the Evaluation page shows the error
            self.eval_error = f"{type(e).__name__}: {e}"
        finally:
            self.evaluating = False

    def stop(self) -> None:
        self._stop = True

    def answer(self, approved: bool, feedback: str = "") -> None:
        self.run.answer({"approved": True} if approved else {"approved": False, "feedback": feedback.strip()})
        self.start()

    def version(self) -> tuple:
        """Changes whenever something new is on screen: the timer fragment reruns the page on a change."""
        return len(self.run.log), self.run.status, self.busy, self.evaluating
