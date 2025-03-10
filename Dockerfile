FROM python:3.10-alpine

# Add mozci source code and setup instructions
WORKDIR /src
COPY LICENSE  poetry.lock  pyproject.toml  README.md ./
COPY mozci /src/mozci/

# Run in a single step to get a small image
RUN apk add --virtual build gcc libffi-dev musl-dev postgresql-dev && \
  # Setup poetry through pip
  pip install --no-cache-dir poetry==1.8.5 && \
  # Install mozci with poetry
  poetry config virtualenvs.create false && \
  poetry install --no-dev --no-interaction --no-ansi && \
  # Cleanup build dependencies
  pip uninstall -y poetry && \
  apk del build && \
  rm -rf /tmp/build

ENTRYPOINT ["mozci"]
