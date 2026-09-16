import io

import boto3
import pandas as pd

from old.config import (
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_ENDPOINT_URL,
    R2_BUCKET_NAME,
    TOP_METHODS_R2_KEY,
)


# ============================================================
# R2 CLIENT
# ============================================================

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
)


# ============================================================
# DOWNLOAD TOP METHODS
# ============================================================

def download_top_methods():
    response = s3.get_object(
        Bucket=R2_BUCKET_NAME,
        Key=TOP_METHODS_R2_KEY,
    )

    data = response[
        "Body"
    ].read()

    return pd.read_parquet(
        io.BytesIO(data)
    )


# ============================================================
# GENERIC PARQUET DOWNLOAD
# ============================================================

def download_parquet(
    key,
):
    response = s3.get_object(
        Bucket=R2_BUCKET_NAME,
        Key=key,
    )

    data = response[
        "Body"
    ].read()

    return pd.read_parquet(
        io.BytesIO(data)
    )


# ============================================================
# GENERIC PARQUET SAVE
# ============================================================

def save_parquet(
    dataframe,
    key,
):
    buffer = io.BytesIO()

    dataframe.to_parquet(
        buffer,
        index=False,
    )

    buffer.seek(0)

    s3.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=key,
        Body=buffer.getvalue(),
        ContentType=(
            "application/octet-stream"
        ),
    )


# ============================================================
# METHOD EQUITY KEY
# ============================================================

def method_equity_key(
    method_id,
):
    return (
        f"live_equity/"
        f"{method_id}.parquet"
    )


# ============================================================
# LOAD METHOD EQUITY
# ============================================================

def load_method_equity(
    method_id,
):
    key = method_equity_key(
        method_id
    )

    try:

        return download_parquet(
            key
        )

    except s3.exceptions.ClientError as error:

        code = (
            error.response
            .get("Error", {})
            .get("Code")
        )

        if code in (
            "404",
            "NoSuchKey",
        ):

            return None

        raise


# ============================================================
# SAVE METHOD EQUITY
# ============================================================

def save_method_equity(
    method_id,
    equity_dataframe,
):
    key = method_equity_key(
        method_id
    )

    save_parquet(
        equity_dataframe,
        key,
    )