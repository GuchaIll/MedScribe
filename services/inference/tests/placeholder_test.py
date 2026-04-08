import pytest


@pytest.mark.integration
def test_inference_service_placeholder():
    pytest.skip(
        "services/inference has no runnable service implementation yet "
        "(services/inference/app/main.py is empty)."
    )
