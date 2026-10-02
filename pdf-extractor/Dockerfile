FROM --platform=linux/amd64 python:3.12.11-slim-bookworm@sha256:c00fc7b44d844b6da22861ec24af43968a5200eac4ec607b4725d585165d6b49

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pdf-extractor/dependencies.lock.json pdf-extractor/build.py /build/
# Only this dedicated image build fetches/installs parser dependencies.
RUN ["/usr/local/bin/python3", "-I", "-B", "/build/build.py"]
COPY pdf-extractor/worker.py pdf-extractor/structure.py pdf-extractor/bounded_json.py pdf-extractor/process.py pdf-extractor/bootstrap.py pdf-extractor/probe.py /worker/
COPY pdf-extractor/supervisor.py pdf-extractor/process.py /supervisor/
COPY api/app/pdf_protocol.py /worker/pdf_protocol.py
COPY api/app/pdf_protocol.py /supervisor/pdf_protocol.py
RUN cp /build/build.json /worker/build.json && cp /build/build.json /supervisor/build.json && rm -rf /build
USER 10002:10002
CMD ["/usr/local/bin/python3", "-I", "-B", "/supervisor/supervisor.py"]
