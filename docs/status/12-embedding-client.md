# Backend embedding client (local)

`backend/src/job_hunter/embedding/` contains a small HTTP client for the standalone service's `POST /v1/embed`
contract. It sends a list of texts and returns the model ID with immutable 512-dimensional vectors. It rejects
blank inputs, fake/missing backends, malformed/truncated responses, non-finite or non-unit vectors, wrong dimensions,
and missing model IDs. Service/HTTP failures are reported as `EmbedderUnavailable` without exposing source text.

The client is **not wired into the API, ingestion, profile saves, database, or ranking**. There is no schema change,
background job, or on-request embedding. The existing recommendation behavior and Compose defaults remain unchanged.
This is the first local stage of the separate recommender plan; job text and metadata need coordination with the
ingestion owner before persistence or retrieval is built. The embedder service can change models behind the same
HTTP contract, but a model change requires re-embedding both jobs and profiles.

Focused verification from the repository root: `py -3 -m pytest backend/tests/test_embedding_client.py
backend/tests/test_recommendations.py -q` passed (17 client tests, 9 existing ranking tests). A local host-side
call to `http://127.0.0.1:8100/v1/embed` through `HttpEmbedder` returned the Jina model ID and one 512-number
vector. This does not prove container-to-container API wiring or AWS/Bedrock deployment. The broad backend test
suite could not collect on the host Python environment because SQLAlchemy, ReportLab and jsonschema are missing;
those dependencies are in the Docker backend image. No unrelated dependencies were installed.
