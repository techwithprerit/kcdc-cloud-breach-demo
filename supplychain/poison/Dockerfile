# A benign "tampered" image used to demonstrate Binary Authorization blocking.
# It starts from the SAME app but injects a backdoor marker and flips BACKDOOR=1,
# which exposes /pwned. It is deliberately built OUTSIDE the signed pipeline, so
# it has no cosign signature and no SLSA provenance -> the secure cluster rejects
# it at admission. The "backdoor" only proves code execution; it does nothing harmful.
FROM python:3.11.9-slim-bookworm
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/main.py .
# marker of tampering — imagine this line was injected by a compromised build step
RUN echo "implant: exfil beacon would go here" > /app/.implant
ENV BACKDOOR=1
EXPOSE 8080
CMD ["python", "main.py"]
