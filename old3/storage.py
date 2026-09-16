# storage.py

import io
import boto3
import pandas as pd

from old3.config import R2_BUCKET


_s3 = boto3.client("s3")


def exists(path):
    try:
        _s3.head_object(Bucket=R2_BUCKET, Key=path)
        return True
    except _s3.exceptions.ClientError:
        return False


def load_parquet(path):
    response = _s3.get_object(Bucket=R2_BUCKET, Key=path)
    return pd.read_parquet(io.BytesIO(response["Body"].read()))


def save_parquet(data, path):
    buffer = io.BytesIO()
    data.to_parquet(buffer, index=False)
    buffer.seek(0)

    _s3.put_object(
        Bucket=R2_BUCKET,
        Key=path,
        Body=buffer.getvalue(),
    )


def delete(path):
    _s3.delete_object(Bucket=R2_BUCKET, Key=path)