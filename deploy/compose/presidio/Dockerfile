# Presidio analyzer (Microsoft, MIT) with German next to English: finds personal data inside
# your network, for the PII slot of a pipeline (adapter "presidio"). Optional service,
# compose profile bundled-presidio. The official image ships spaCy 3.8 and English only.
FROM mcr.microsoft.com/presidio-analyzer:2.2.362

USER root
# German NER model, pinned to the version that matches the image's spaCy 3.8.
RUN pip install --no-cache-dir \
    https://github.com/explosion/spacy-models/releases/download/de_core_news_md-3.8.0/de_core_news_md-3.8.0-py3-none-any.whl
COPY nlp.yaml analyzer.yaml recognizers.yaml /app/veyntora/
ENV NLP_CONF_FILE=veyntora/nlp.yaml \
    ANALYZER_CONF_FILE=veyntora/analyzer.yaml \
    RECOGNIZER_REGISTRY_CONF_FILE=veyntora/recognizers.yaml
USER 1001
