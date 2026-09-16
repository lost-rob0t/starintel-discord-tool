FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN useradd --create-home --uid 10001 starintel && mkdir -p /var/lib/starintel-discord && chown -R starintel:starintel /var/lib/starintel-discord
USER starintel
ENV STARINTEL_DISCORD_CONFIG=/etc/starintel-discord/config.toml
ENTRYPOINT ["starintel-discord"]
