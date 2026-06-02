"""SWE-bench evaluator for the unified agents CLI.

Per-task `evaluate(task_meta, patch)` accumulates into an in-process
predictions buffer; on the first call it returns score=0/passed=False
(pending). The CLI runs `finalize()` after the loop to call
`swebench.harness.run_evaluation` once on all collected patches, then
patches each row's eval fields in results.jsonl.

Registered name: "swebench".

`task_meta` must include `eval_config.instance_id` (set by the
unified_runner swe_bench_lite/pro loader).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_cap.agents.evaluators import EvalResult, register_evaluator


@register_evaluator("swebench")
class SWEBenchEvaluator:
    def __init__(
        self,
        dataset: str = "princeton-nlp/SWE-bench_Lite",
        run_id: str = "agentcap_unified",
        max_workers: int = 8,
        model_name: str = "agentcap-unified",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id
        self.max_workers = int(max_workers)
        self.model_name = str(model_name).replace("/", "-").replace(":", "-")
        self._buffer: Dict[str, str] = {}
        self._lock = threading.Lock()

    def evaluate(self, task_meta: Dict[str, Any], output_text: str) -> EvalResult:
        eval_cfg = (task_meta.get("eval_config") or {})
        iid = eval_cfg.get("instance_id") or task_meta.get("instance_id") or ""
        if not iid:
            return EvalResult(
                passed=False, score=0.0,
                details={"evaluator": "swebench", "error": "missing instance_id"},
            )
        if not output_text.strip():
            return EvalResult(
                passed=False, score=0.0,
                details={"evaluator": "swebench", "error": "empty patch", "instance_id": iid},
            )
        with self._lock:
            self._buffer[iid] = output_text
        return EvalResult(
            passed=False, score=0.0,
            details={"evaluator": "swebench", "instance_id": iid, "status": "pending"},
        )

    def finalize(self, out_dir: Path) -> Dict[str, Dict[str, Any]]:
        if not self._buffer:
            return {}
        preds = [
            {"instance_id": iid, "model_patch": patch, "model_name_or_path": self.model_name}
            for iid, patch in self._buffer.items()
        ]
        preds_path = out_dir / "predictions.json"
        preds_path.write_text(json.dumps(preds, indent=2))
        cmd = [
            sys.executable, "-m", "swebench.harness.run_evaluation",
            "--dataset_name", self.dataset,
            "--predictions_path", str(preds_path),
            "--max_workers", str(self.max_workers),
            "--run_id", self.run_id,
            "--cache_level", "instance",
        ]
        log_path = out_dir / "swebench_eval.log"
        with open(log_path, "w") as lf:
            subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=3600 * 6)
        reports_dir = Path("logs/run_evaluation") / self.run_id
        results: Dict[str, Dict[str, Any]] = {}
        if reports_dir.exists():
            for model_dir in reports_dir.glob("*"):
                for rep in model_dir.glob("*/report.json"):
                    iid = rep.parent.name
                    try:
                        info = json.loads(rep.read_text()).get(iid, {})
                        results[iid] = {
                            "resolved": bool(info.get("resolved")),
                            "details": info,
                        }
                    except Exception:
                        pass
        return results
