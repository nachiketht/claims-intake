# Claims Intake Service

The claims intake service accepts a first notice of loss from the claims portal, validates it against the policy master and the rule table in `docs/api-contract.md`, and either records a notification and issues a claim reference or refuses the submission with a specific reason. It does not decide whether the claim will be paid.

## Running the service

Inside a Linux container with Docker available, build an amd64 image and publish port 8000:

```
docker buildx build --platform linux/amd64 -t claims-intake .
docker run -p 8000:8000 claims-intake
```

The service listens on port 8000. Submit a notification with `POST /notifications`. A well-formed, admissible body returns `201` and a claim reference; a refused body returns the error envelope from the contract.

## Why `--platform linux/amd64`

Docker tags an image with the CPU architecture of the machine that built it, unless you say otherwise. This environment, and many developer laptops (Apple Silicon in particular), are arm64. The servers and CI runners that later pull the image are almost always amd64 (x86_64). An arm64 image cannot run on an amd64 host: the two instruction sets are not interchangeable, so the kernel refuses to start the process.

`--platform linux/amd64` forces the build to produce the amd64 image those machines expect. On an arm64 host Docker emulates amd64 for the build, which is slower, but the resulting image will actually start where it is deployed.

## Running the tests

Dependencies are already installed in this environment. From the repository root:

```
uv run pytest
```

Unit tests live under `tests/unit/`. Integration tests under `tests/integration/` hit the HTTP surface.

## Data

Everything in `data/` is synthetic and was authored for this program. It contains no real client data and no named clients.
