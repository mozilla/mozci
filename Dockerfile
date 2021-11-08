FROM python:3.9-alpine

# Add mozci source code and setup instructions
WORKDIR /src
COPY LICENSE  poetry.lock  pyproject.toml  README.md ./
COPY mozci /src/mozci/

# Run in a single step to get a small image
RUN apk add --virtual build gcc libffi-dev musl-dev postgresql-dev && \
  # Setup latest poetry through pip
  pip install poetry && \
  # Install mozci with poetry
  poetry config virtualenvs.create false && \
  poetry install --no-dev --no-interaction --no-ansi && \
  # Cleanup build dependencies
  apk del build && \
  rm -rf /tmp/build
