# data_storage.py

import io
import os

import boto3
import pandas as pd


# ============================================================
# R2 CONNECTION
# ============================================================

R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")

R2_BUCKET = "stocks-data"


s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
)


# ============================================================
# PARQUET
# ============================================================

def load_parquet(path):
    """
    Input:
        path: R2 object path

    Description:
        Loads a Parquet file from R2 into a pandas DataFrame.

    Output:
        pandas.DataFrame
    """

    response = s3.get_object(
        Bucket=R2_BUCKET,
        Key=path,
    )

    data = response["Body"].read()

    return pd.read_parquet(io.BytesIO(data))


def save_parquet(dataframe, path):
    """
    Input:
        dataframe: pandas.DataFrame
        path: R2 object path

    Description:
        Saves a DataFrame as a Parquet file to R2,
        replacing the existing file if it exists.

    Output:
        None
    """

    buffer = io.BytesIO()

    dataframe.to_parquet(
        buffer,
        index=False,
    )

    buffer.seek(0)

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=path,
        Body=buffer.getvalue(),
    )


# ============================================================
# FILE EXISTENCE
# ============================================================

def parquet_exists(path):
    """
    Input:
        path: R2 object path

    Description:
        Checks whether a file exists in R2.

    Output:
        bool
    """

    try:
        s3.head_object(
            Bucket=R2_BUCKET,
            Key=path,
        )

        return True

    except Exception:
        return False


# ============================================================
# LOAD OR CREATE
# ============================================================

def load_or_create_parquet(path, columns=None):
    """
    Input:
        path: R2 object path
        columns: optional list of DataFrame columns

    Description:
        Loads an existing Parquet file.
        If it does not exist, creates an empty DataFrame.

    Output:
        pandas.DataFrame
    """

    if parquet_exists(path):
        return load_parquet(path)

    if columns is None:
        return pd.DataFrame()

    return pd.DataFrame(columns=columns)


# ============================================================
# TEXT FILES
# ============================================================

def load_text(path):
    """
    Load a UTF-8 text file from R2.
    """

    response = s3.get_object(
        Bucket=R2_BUCKET,
        Key=path,
    )

    body = response["Body"].read()

    return body.decode("utf-8")


def save_text(text, path):
    """
    Save a UTF-8 text file to R2.
    """

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=path,
        Body=text.encode("utf-8"),
        ContentType="text/plain",
    )