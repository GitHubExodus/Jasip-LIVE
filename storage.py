"""
storage.py - Parquet & Cloudflare R2 Persistence Module
Provides thread-safe loading and saving of stock equity Parquet files 
and global contribution Parquet files with local caching fallbacks.
"""

from typing import Optional, Dict, Any, Union
import io
import os
import logging
import threading
import pandas as pd
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

import config

logger = logging.getLogger("StorageModule")

# Local cache directory for resilience during network interruptions
LOCAL_CACHE_DIR = getattr(config, "LOCAL_CACHE_DIR", ".storage_cache")

# ==========================================
# ========= Start: 8.3 R2 File Management =============
# ==========================================

class R2Manager:
    """Manages low-level S3/R2 client initialization and raw byte transfers."""

    def __init__(self) -> None:
        """Initialize the boto3 S3 client targeted at Cloudflare R2."""
        self.bucket_name: str = getattr(config, "R2_BUCKET_NAME", "trading-bucket")
        
        # Configure client with standard s3v4 signature for R2 compatibility
        s3_config = Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"}
        )
        
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=getattr(config, "R2_ENDPOINT_URL", None),
            aws_access_key_id=getattr(config, "R2_ACCESS_KEY_ID", None),
            aws_secret_access_key=getattr(config, "R2_SECRET_ACCESS_KEY", None),
            config=s3_config,
            region_name="auto"
        )

    def download_bytes(self, key: str) -> Optional[bytes]:
        """Download raw file bytes from R2 key. Returns None if key does not exist."""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return response["Body"].read()
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404"):
                return None
            logger.warning(f"Failed to download key '{key}' from R2: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading '{key}': {e}")
            return None

    def upload_bytes(self, data_bytes: bytes, key: str) -> bool:
        """Upload raw file bytes to R2 key, replacing any existing object."""
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=data_bytes,
                ContentType="application/octet-stream"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to upload key '{key}' to R2: {e}")
            return False

    def object_exists(self, key: str) -> bool:
        """Check whether a key exists in the R2 bucket."""
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return False
            logger.warning(f"Error checking key '{key}' in R2: {e}")
            return False
        except Exception:
            return False

# ==========================================
# ======= End: 8.3 R2 File Management =======
# ==========================================


# ==========================================
# ========= Start: 8.1 Generic Parquet Read =============
# ==========================================

def read_parquet_from_r2(r2_manager: R2Manager, key: str) -> Optional[pd.DataFrame]:
    """
    Downloads raw bytes for a key from R2 and deserializes them into a pandas DataFrame.
    Falls back to local cache if R2 download fails.
    """
    data_bytes = r2_manager.download_bytes(key)
    if data_bytes is not None:
        try:
            buffer = io.BytesIO(data_bytes)
            df = pd.read_parquet(buffer)
            # Update local cache on successful fetch
            _write_local_cache(key, data_bytes)
            return df
        except Exception as e:
            logger.error(f"Error parsing Parquet bytes from R2 key '{key}': {e}")

    # Fallback to local disk cache if remote fetch yields None/fails
    return _read_local_cache(key)

# ==========================================
# ======= End: 8.1 Generic Parquet Read =======
# ==========================================


# ==========================================
# ========= Start: 8.2 Generic Parquet Write =============
# ==========================================

def write_parquet_to_r2(r2_manager: R2Manager, df: pd.DataFrame, key: str) -> None:
    """
    Serializes a pandas DataFrame into Parquet format in memory, uploads it to R2,
    and writes to local storage cache for redundant backup.
    """
    if df is None or df.empty:
        logger.warning(f"Skipping write for empty DataFrame to key '{key}'.")
        return

    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False, engine="pyarrow")
    raw_bytes = buffer.getvalue()

    # Always persist locally first
    _write_local_cache(key, raw_bytes)

    # Attempt remote upload
    success = r2_manager.upload_bytes(raw_bytes, key)
    if not success:
        logger.warning(f"Key '{key}' saved to local cache but failed R2 remote sync.")

# ==========================================
# ======= End: 8.2 Generic Parquet Write =======
# ==========================================


# Local Disk Backup Helpers
def _get_local_cache_path(key: str) -> str:
    clean_key = key.replace("/", "_")
    return os.path.join(LOCAL_CACHE_DIR, clean_key)

def _write_local_cache(key: str, data_bytes: bytes) -> None:
    try:
        os.makedirs(LOCAL_CACHE_DIR, exist_ok=True)
        path = _get_local_cache_path(key)
        with open(path, "wb") as f:
            f.write(data_bytes)
    except Exception as e:
        logger.debug(f"Failed writing local cache for {key}: {e}")

def _read_local_cache(key: str) -> Optional[pd.DataFrame]:
    path = _get_local_cache_path(key)
    if os.path.exists(path):
        try:
            logger.info(f"Loading '{key}' from local cache fallback.")
            return pd.read_parquet(path)
        except Exception as e:
            logger.error(f"Failed reading local cache at {path}: {e}")
    return None


# Data Conversion Adapters (EquityData <-> DataFrame)
def _equity_data_to_df(equity_data: Any) -> pd.DataFrame:
    """Converts an EquityData dataclass instance or dict to a pandas DataFrame."""
    if isinstance(equity_data, pd.DataFrame):
        return equity_data
    if hasattr(equity_data, "to_dataframe"):
        return equity_data.to_dataframe()
    if hasattr(equity_data, "trades"):
        return pd.DataFrame(equity_data.trades)
    if isinstance(equity_data, dict):
        return pd.DataFrame(equity_data)
    return pd.DataFrame()

def _df_to_equity_data(df: Optional[pd.DataFrame]) -> Any:
    """Converts a pandas DataFrame back into an EquityData structured object if available."""
    if df is None:
        try:
            from equity import EquityData
            return EquityData()
        except ImportError:
            return pd.DataFrame()
    
    try:
        from equity import EquityData
        if hasattr(EquityData, "from_dataframe"):
            return EquityData.from_dataframe(df)
        return EquityData(trades=df.to_dict(orient="records"))
    except Exception:
        return df


# ==========================================
# ========= Start: 8.4 Equity Storage =============
# ==========================================

def load_stock_equity(r2_manager: R2Manager, symbol: str) -> Optional[pd.DataFrame]:
    """
    Loads the equity Parquet DataFrame for a specific stock symbol.
    R2 Key pattern: stocks-data/equity/{symbol}.parquet
    """
    prefix = getattr(config, "R2_EQUITY_PREFIX", "stocks-data/equity")
    key = f"{prefix}/{symbol}.parquet"
    return read_parquet_from_r2(r2_manager, key)

def save_stock_equity(r2_manager: R2Manager, symbol: str, df: pd.DataFrame) -> None:
    """
    Saves/replaces the equity Parquet DataFrame for a specific stock symbol.
    R2 Key pattern: stocks-data/equity/{symbol}.parquet
    """
    prefix = getattr(config, "R2_EQUITY_PREFIX", "stocks-data/equity")
    key = f"{prefix}/{symbol}.parquet"
    write_parquet_to_r2(r2_manager, df, key)

# ==========================================
# ======= End: 8.4 Equity Storage =======
# ==========================================


# ==========================================
# ========= Start: 8.5 Contribution Storage =============
# ==========================================

def load_global_contributions(r2_manager: R2Manager) -> Optional[pd.DataFrame]:
    """
    Loads the single global contribution history Parquet DataFrame.
    R2 Key pattern: stocks-data/contributions/contributions.parquet
    """
    key = getattr(config, "R2_CONTRIBUTIONS_KEY", "stocks-data/contributions/contributions.parquet")
    return read_parquet_from_r2(r2_manager, key)

def save_global_contributions(r2_manager: R2Manager, df: pd.DataFrame) -> None:
    """
    Saves/replaces the global contribution history Parquet DataFrame.
    R2 Key pattern: stocks-data/contributions/contributions.parquet
    """
    key = getattr(config, "R2_CONTRIBUTIONS_KEY", "stocks-data/contributions/contributions.parquet")
    write_parquet_to_r2(r2_manager, df, key)

# ==========================================
# ======= End: 8.5 Contribution Storage =======
# ==========================================


# ==========================================
# ========= Start: 8.6 Storage Interface =============
# ==========================================

class StorageEngine:
    """
    Public storage API encapsulating R2 operations for equity and contribution files.
    Hides internal R2/Parquet mechanics from morning.py, live.py, and equity.py.
    """

    def __init__(self, r2_manager: Optional[R2Manager] = None) -> None:
        """Initialize the storage interface with an optional custom R2Manager instance."""
        self.r2_manager = r2_manager if r2_manager is not None else R2Manager()

    def get_equity(self, symbol: str) -> Optional[pd.DataFrame]:
        """Retrieve equity curve records for a specific stock symbol."""
        return load_stock_equity(self.r2_manager, symbol)

    def save_equity(self, symbol: str, df: pd.DataFrame) -> None:
        """Store/update equity curve records for a specific stock symbol."""
        save_stock_equity(self.r2_manager, symbol, df)

    def get_contributions(self) -> Optional[pd.DataFrame]:
        """Retrieve the global contribution records for all methods."""
        return load_global_contributions(self.r2_manager)

    def save_contributions(self, df: pd.DataFrame) -> None:
        """Store/update the global contribution records."""
        save_global_contributions(self.r2_manager, df)

    def equity_file_exists(self, symbol: str) -> bool:
        """Check if an equity curve file exists for a specific stock symbol."""
        prefix = getattr(config, "R2_EQUITY_PREFIX", "stocks-data/equity")
        key = f"{prefix}/{symbol}.parquet"
        return self.r2_manager.object_exists(key)

# ==========================================
# ======= End: 8.6 Storage Interface =======
# ==========================================


# ==========================================
# Thread-Safe Global Instance & Top-Level Wrappers
# ==========================================

_DEFAULT_ENGINE: Optional[StorageEngine] = None
_LOCK = threading.Lock()

def get_storage_engine() -> StorageEngine:
    """Thread-safe access to default StorageEngine instance."""
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        with _LOCK:
            if _DEFAULT_ENGINE is None:
                _DEFAULT_ENGINE = StorageEngine()
    return _DEFAULT_ENGINE

def load_equity(symbol: str) -> Any:
    """
    Top-level helper for morning.py / equity.py.
    Returns EquityData object or DataFrame depending on environment.
    """
    engine = get_storage_engine()
    df = engine.get_equity(symbol)
    return _df_to_equity_data(df)

def save_equity(symbol: str, equity_data: Any) -> None:
    """
    Top-level helper for morning.py / equity.py.
    Accepts either EquityData dataclass or raw DataFrame.
    """
    engine = get_storage_engine()
    df = _equity_data_to_df(equity_data)
    engine.save_equity(symbol, df)

def load_contributions() -> Optional[pd.DataFrame]:
    """Top-level helper for morning.py to load global contributions."""
    engine = get_storage_engine()
    return engine.get_contributions()

def save_contributions(contributions: Any) -> None:
    """Top-level helper for morning.py to persist global contributions."""
    engine = get_storage_engine()
    if isinstance(contributions, pd.DataFrame):
        df = contributions
    elif hasattr(contributions, "to_dataframe"):
        df = contributions.to_dataframe()
    elif isinstance(contributions, dict):
        df = pd.DataFrame(contributions)
    else:
        df = pd.DataFrame(contributions)
    engine.save_contributions(df)