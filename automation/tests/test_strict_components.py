from __future__ import annotations

import pytest

from automation.loop.platform_eval import PlatformEvaluator


def test_platform_upload_is_explicit_and_fail_closed(tmp_path) -> None:
    evaluator = PlatformEvaluator()
    with pytest.raises(FileNotFoundError, match="不存在"):
        evaluator.upload_artifact(tmp_path / "missing.ipynb")
    invalid = tmp_path / "factor.txt"
    invalid.write_text("not a notebook", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持"):
        evaluator.upload_artifact(invalid)
