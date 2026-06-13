# tests/conftest.py
import socket, uuid, boto3, httpx, pytest
from libs.audit.oss_audit import oss_boto3_config


def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def minio_s3():
    if not _reachable("localhost", 9000):
        pytest.skip("MinIO 未启动（先 `make dev-up`）")
    return boto3.client("s3", endpoint_url="http://localhost:9000",
                        aws_access_key_id="minio", aws_secret_access_key="minio123",
                        region_name="us-east-1",
                        config=oss_boto3_config("http://localhost:9000"))


@pytest.fixture
def minio_bucket(minio_s3):
    name = f"it-{uuid.uuid4().hex[:8]}"
    minio_s3.create_bucket(Bucket=name)
    yield name
    for o in minio_s3.list_objects_v2(Bucket=name).get("Contents", []):
        minio_s3.delete_object(Bucket=name, Key=o["Key"])
    minio_s3.delete_bucket(Bucket=name)


@pytest.fixture(scope="session")
def gravitino_url():
    if not _reachable("localhost", 8091):
        pytest.skip("Gravitino 未启动（先 `make up` 或 `docker compose -f deploy/dev/gravitino.yml up -d`）")
    return "http://localhost:8091"


@pytest.fixture(scope="session")
def kc_token():
    if not _reachable("localhost", 8080):
        pytest.skip("Keycloak 未启动（先 `make dev-up`）")
    r = httpx.post("http://localhost:8080/realms/lite-ai/protocol/openid-connect/token",
                   data={"client_id": "gateway", "client_secret": "dev-secret",
                         "username": "alice", "password": "alice", "grant_type": "password"})
    r.raise_for_status()
    return r.json()["access_token"]
