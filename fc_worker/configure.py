from __future__ import annotations

import os

from alibabacloud_fc20230330 import models as fc_models
from alibabacloud_fc20230330.client import Client
from alibabacloud_tea_openapi import models as open_api_models


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"missing environment variable: {name}")
    return value


def main() -> None:
    endpoint = required("SRT_FC_ENDPOINT")
    function_name = required("SRT_FC_FUNCTION_NAME")
    qualifier = os.getenv("SRT_FC_QUALIFIER", "LATEST").strip() or "LATEST"
    config = open_api_models.Config(
        access_key_id=required("ALIBABA_CLOUD_ACCESS_KEY_ID"),
        access_key_secret=required("ALIBABA_CLOUD_ACCESS_KEY_SECRET"),
        security_token=os.getenv("ALIBABA_CLOUD_SECURITY_TOKEN", "").strip() or None,
        endpoint=endpoint,
    )
    client = Client(config)
    client.put_async_invoke_config(
        function_name,
        fc_models.PutAsyncInvokeConfigRequest(
            qualifier=qualifier,
            body=fc_models.PutAsyncInvokeConfigInput(
                async_task=True,
                max_async_event_age_in_seconds=86400,
                max_async_retry_attempts=0,
            ),
        ),
    )
    client.put_concurrency_config(
        function_name,
        fc_models.PutConcurrencyConfigRequest(
            body=fc_models.PutConcurrencyInput(reserved_concurrency=1),
        ),
    )
    client.put_scaling_config(
        function_name,
        fc_models.PutScalingConfigRequest(
            qualifier=qualifier,
            body=fc_models.PutScalingConfigInput(
                enable_on_demand_scaling=True,
                min_instances=0,
            ),
        ),
    )
    print(
        "configured async task mode, zero retries, 24h queue lifetime, "
        "concurrency 1, and minimum instances 0"
    )


if __name__ == "__main__":
    main()
