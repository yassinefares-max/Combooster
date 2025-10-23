# ScrapingApp/Dockerfile (version légère)
FROM python:3.11-slim

WORKDIR /app

# Installer les dépendances système minimales
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    python3-dev \
    wget \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Installer Chromium et ses dépendances directement
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-l10n \
    chromium-sandbox \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libxss1 \
    libasound2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copier le requirements.txt depuis la racine
COPY requirements.txt .

# Installer toutes les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Installer Playwright pour Chromium uniquement
RUN pip install playwright && \
    playwright install chromium

# Copier l'application ScrapingApp
COPY ScrapingApp/ .

# Variables d'environnement
ENV FLASK_APP=app5.py
ENV FLASK_ENV=production
ENV PYTHONPATH=/app

# Définir Chromium comme browser par défaut
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV CHROMIUM_PATH=/usr/bin/chromium

# Exposer le port
EXPOSE 5000

CMD ["python", "app5.py"]