import os
import io
import csv
import json
import time
import re
import urllib.parse
from collections import deque
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from bs4 import BeautifulSoup
import tldextract
import requests
from rag_system import initialize_rag_system, get_rag_system,initialize_rag
from extra_routes import extra_routes
import hashlib


MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

# Playwright import (sync)
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change_this_secret_please_change")

app.register_blueprint(extra_routes)

# CONFIG par défaut
DEFAULT_MAX_PAGES = 50
DEFAULT_MAX_DEPTH = 2
REQUEST_TIMEOUT = 20  # secondes pour requests
PLAYWRIGHT_TIMEOUT = 30000  # ms pour playwright

# Utilitaires
def same_domain(url1, url2):
    e1 = tldextract.extract(url1)
    e2 = tldextract.extract(url2)
    return (e1.domain, e1.suffix) == (e2.domain, e2.suffix)

def normalize_link(base, link):
    if not link:
        return None
    link = link.split('#')[0].strip()
    if link.startswith("javascript:") or link.startswith("mailto:"):
        return None
    return urllib.parse.urljoin(base, link)

def extract_products(html, url):
    """Extrait les informations des produits avec une détection avancée"""
    soup = BeautifulSoup(html, "html.parser")
    products = []
    
    # APPROCHE 1: Sélecteurs CSS étendus pour toutes les plateformes
    products.extend(extract_with_css_selectors(soup, url))
    
    # APPROCHE 2: Détection par contenu pour les sites complexes
    if len(products) < 2:  # Si peu de produits trouvés
        products.extend(extract_with_content_analysis(soup, url))
    
    # APPROCHE 3: Détection par grilles et listes
    products.extend(extract_with_grid_detection(soup, url))
    
    # APPROCHE 4: Détection par données structurées
    products.extend(extract_from_structured_data(soup, url))
    
    # Dédupliquer les produits
    return deduplicate_products(products)

def extract_with_css_selectors(soup, url):
    """Extraction avec une gamme très étendue de sélecteurs CSS"""
    products = []
    
    # Sélecteurs complets pour toutes les plateformes e-commerce
    selectors = [
        # PrestaShop
        '.product-miniature', '.ajax_block_product', '.product-container',
        '.product-box', '.item', '.product-item', '.product-thumbnail',
        
        # WooCommerce
        '.product', '.type-product', '.woocommerce-product',
        '.wc-product', '.product-type-simple', '.product-type-variable',
        
        # Shopify
        '.grid__item', '.product-grid-item', '.collection-item',
        '.product-item', '.product-card', '.product-block',
        
        # Magento
        '.product-item-info', '.product-item-details',
        '.product-image-container', '.product-item-photo',
        
        # BigCommerce
        '.productBlock', '.productList', '.product',
        
        # Squarespace
        '.product', '.product-item', '.grid-product',
        
        # Wix
        '.product-item', '.product-wrapper', '.product-content',
        
        # Generic e-commerce
        '.product', '.item', '.card', '.product-item', '.product-card',
        '.goods-item', '.product-grid-item', '.shop-item', '.catalog-item',
        '.store-item', '.boutique-item', '.commerce-item',
        
        # French e-commerce
        '.produit', '.article', '.item-produit', '.carte-produit',
        '.boutique-produit', '.produit-item', '.article-produit',
        '.fiche-produit', '.liste-produit',
        
        # Data attributes
        '[data-product]', '[data-item]', '[data-product-id]',
        '[data-product-name]', '[data-product-price]',
        
        # Class patterns
        '[class*="product"]', '[class*="item"]', '[class*="card"]',
        '[class*="article"]', '[class*="goods"]', '[class*="shop"]',
        '[class*="catalog"]', '[class*="store"]', '[class*="commerce"]',
        
        # List items
        'li.product', 'li.item', 'li.product-item', 'li.goods-item',
        'li.shop-item', 'li.catalog-item',
        
        # Div items
        'div.product', 'div.item', 'div.product-item', 'div.goods-item',
        'div.shop-item', 'div.catalog-item',
        
        # Article items
        'article.product', 'article.item', 'article.product-item',
        
        # Section items
        'section.product', 'section.item', 'section.product-item',
        
        # Specific to problematic sites
        '.elementor-widget', '.vc_column_container', '.module',
        '.content', '.block', '.widget', '.component'
    ]
    
    for selector in selectors:
        try:
            elements = soup.select(selector)
            for element in elements:
                product_data = extract_product_data_from_element(element, url)
                if product_data and product_data.get('name'):
                    products.append(product_data)
        except Exception:
            continue
    
    return products

# ================================
# FONCTIONS POUR PRODUITS PROMUS (intégrées depuis app_promotions.py)
# ================================

def extract_promoted_products(html, base_url):
    """Extrait les produits promus avec une détection avancée"""
    soup = BeautifulSoup(html, "html.parser")
    found_products = []
    
    # Sélecteurs pour produits promus
    PROMOTED_SELECTORS = [
        '.promoted', '.featured', '.highlighted', '.special', '.banner-product',
        '.main-product', '.hero-product', '.spotlight', '.showcase',
        '[data-promoted]', '[data-featured]', '.new', '.nouveau',
        '.best-seller', '.best-seller', '.top-product'
    ]
    
    # Recherche dans les sélecteurs de promotion
    for selector in PROMOTED_SELECTORS:
        try:
            elements = soup.select(selector)
            for element in elements:
                product_data = extract_promoted_product_data(element, base_url)
                if product_data and product_data.get('name'):
                    found_products.append(product_data)
        except Exception:
            continue
    
    # Si peu de produits promus trouvés, chercher dans les sections principales
    if len(found_products) < 3:
        main_sections = soup.select('.main, .hero, .banner, .header, section')
        for section in main_sections:
            products = extract_products_from_section(section, base_url)
            found_products.extend(products)
    
    # Marquer explicitement tous les produits comme promus
    for product_data in found_products:
        product_data['is_promoted'] = True
        product_data['promotion_detected'] = True
        # S'assurer que les indicateurs de promotion existent
        if 'promotion_indicators' not in product_data:
            product_data['promotion_indicators'] = ['auto_detected']
    
    # Dédupliquer
    unique_products = []
    seen = set()
    for product in found_products:
        key = f"{product.get('name', '').lower()}|{product.get('product_url', '')}"
        if key not in seen and product.get('name'):
            seen.add(key)
            unique_products.append(product)
    
    return unique_products

def extract_promoted_product_data(element, base_url):
    """Extrait les données d'un produit promu"""
    product_data = {}
    
    # Nom
    name = extract_promoted_product_name(element)
    if name:
        product_data['name'] = name
    
    # Prix
    price = extract_promoted_product_price(element)
    if price:
        product_data['price'] = price
    
    # Description
    description = extract_promoted_product_description(element)
    if description:
        product_data['description'] = description
    
    # Image
    image = extract_promoted_product_image(element, base_url)
    if image:
        product_data['image'] = image
    
    # URL produit
    product_url = extract_promoted_product_url(element, base_url)
    if product_url:
        product_data['product_url'] = product_url
    
    # Détection de promotion
    promotion_indicators = detect_promotion_indicators(element)
    if promotion_indicators:
        product_data['promotion_indicators'] = promotion_indicators
    
    return product_data

def extract_promoted_product_name(element):
    """Extrait le nom d'un produit promu"""
    name_selectors = [
        'h1', 'h2', 'h3', '.product-name', '.title', '.name',
        '.promo-title', '.featured-title', '.banner-title',
        '[data-product-name]', '.heading', '.title-promo'
    ]
    
    for selector in name_selectors:
        name_elem = element.select_one(selector)
        if name_elem:
            name = name_elem.get_text(strip=True)
            if 3 <= len(name) <= 200:
                return name
    
    # Fallback: chercher dans tout l'élément
    text_content = element.get_text(strip=True)
    lines = [line.strip() for line in text_content.split('\n') if line.strip()]
    for line in lines:
        if 5 <= len(line) <= 100 and not line.isdigit():
            return line
    
    return None

def extract_promoted_product_price(element):
    """Extrait le prix d'un produit promu"""
    price_selectors = [
        '.price', '.promo-price', '.special-price', '.discount-price',
        '.new-price', '.current-price', '.price-tag', '.cost'
    ]
    
    for selector in price_selectors:
        price_elem = element.select_one(selector)
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            price_match = re.search(r'[\d]+[.,\s]*\d*[.,\s]*\d+', price_text)
            if price_match:
                return price_text.strip()
    
    # Fallback: chercher par regex dans tout l'élément
    element_text = element.get_text()
    price_match = re.search(r'[\d]+[.,\s]*\d*[.,\s]*\d+', element_text)
    if price_match:
        return price_match.group(0).strip()
    
    return None

def extract_promoted_product_description(element):
    """Extrait la description d'un produit promu"""
    desc_selectors = [
        '.description', '.promo-desc', '.featured-desc', '.product-desc',
        '.excerpt', '.summary', '.desc', '.text-content'
    ]
    
    for selector in desc_selectors:
        desc_elem = element.select_one(selector)
        if desc_elem:
            desc_text = desc_elem.get_text(strip=True)
            if desc_text:
                return desc_text[:300]
    
    return None

def extract_promoted_product_image(element, base_url):
    """Extrait l'image d'un produit promu"""
    img_selectors = [
        'img', '.product-image', '.promo-image', '.featured-image',
        '.banner-image', '.main-image', '.hero-image'
    ]
    
    for selector in img_selectors:
        img_elem = element.select_one(selector)
        if img_elem:
            src = (img_elem.get('src') or 
                  img_elem.get('data-src') or 
                  img_elem.get('data-original'))
            if src and not src.startswith('data:'):
                return urllib.parse.urljoin(base_url, src)
    
    return None

def extract_promoted_product_url(element, base_url):
    """Extrait l'URL d'un produit promu"""
    link_selectors = [
        'a', '.product-link', '.promo-link', '.featured-link',
        '.banner-link', '.cta-button', '.btn', '.button'
    ]
    
    for selector in link_selectors:
        link_elem = element.select_one(selector)
        if link_elem and link_elem.get('href'):
            href = link_elem.get('href')
            if href and not href.startswith(('javascript:', '#')):
                return urllib.parse.urljoin(base_url, href)
    
    return None

def detect_promotion_indicators(element):
    """Détecte les indicateurs de promotion"""
    indicators = []
    element_text = element.get_text().lower()
    element_classes = ' '.join(element.get('class', [])).lower()
    
    # Mots-clés de promotion
    promotion_keywords = [
        'promo', 'promotion', 'sale', 'solde', 'reduction', 'discount',
        'offre', 'special', 'spécial', 'new', 'nouveau', 'nouvelle',
        'limited', 'limitée', 'exclusif', 'exclusive', 'best', 'top',
        'featured', 'vedette', 'highlight', 'spotlight', 'banner',
        'hero', 'main', 'principal'
    ]
    
    for keyword in promotion_keywords:
        if (keyword in element_text or 
            keyword in element_classes or 
            keyword in str(element.get('id', '')).lower()):
            indicators.append(keyword)
    
    # Indicateurs visuels (badges, labels)
    badge_selectors = ['.badge', '.label', '.tag', '.ribbon', '.sticker']
    for selector in badge_selectors:
        if element.select_one(selector):
            indicators.append('badge_present')
            break
    
    return indicators

def extract_products_from_section(section, base_url):
    """Extrait les produits d'une section principale"""
    products = []
    
    # Chercher les éléments qui ressemblent à des produits
    product_like_elements = section.find_all(['div', 'article', 'li'], 
                                           class_=re.compile(r'product|item|card'))
    
    for element in product_like_elements:
        product_data = extract_promoted_product_data(element, base_url)
        if product_data and product_data.get('name'):
            products.append(product_data)
    
    return products


def extract_with_content_analysis(soup, url):
    """Analyse de contenu pour détecter les produits par leur structure"""
    products = []
    
    # Recherche d'éléments qui ressemblent à des produits
    potential_elements = soup.find_all(['div', 'article', 'li', 'section', 'tr'])
    
    for element in potential_elements:
        # Analyser le contenu de l'élément
        if is_likely_product_element(element):
            product_data = extract_product_data_from_content(element, url)
            if product_data and product_data.get('name'):
                products.append(product_data)
    
    return products

def extract_with_grid_detection(soup, url):
    """Détection des produits dans les grilles et listes"""
    products = []
    
    # Chercher les conteneurs de grille
    grid_indicators = ['grid', 'list', 'products', 'items', 'catalog', 'shop', 'row', 'cols']
    grid_containers = []
    
    for element in soup.find_all(['div', 'section', 'ul']):
        element_classes = element.get('class', [])
        element_id = element.get('id', '')
        element_text = element.get_text().lower()
        
        # Vérifier si c'est un conteneur de grille
        is_grid_container = (
            any(indicator in str(element_classes).lower() for indicator in grid_indicators) or
            any(indicator in element_id.lower() for indicator in grid_indicators) or
            any(indicator in element_text for indicator in ['produit', 'product', 'article', 'item'])
        )
        
        if is_grid_container:
            grid_containers.append(element)
    
    # Analyser les éléments dans les grilles
    for container in grid_containers:
        children = container.find_all(['div', 'article', 'li', 'section'])
        for child in children:
            if is_likely_product_element(child):
                product_data = extract_product_data_from_content(child, url)
                if product_data and product_data.get('name'):
                    products.append(product_data)
    
    return products

def extract_from_structured_data(soup, url):
    """Extraction depuis les données structurées"""
    products = []
    
    # JSON-LD
    script_tags = soup.find_all('script', type='application/ld+json')
    for script in script_tags:
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                data = [data]
            
            for item in data if isinstance(data, list) else [data]:
                if item.get('@type') in ['Product', 'IndividualProduct', 'ProductGroup']:
                    product_data = {
                        'name': item.get('name', ''),
                        'price': extract_price_from_structured_data(item),
                        'description': item.get('description', '')[:200],
                        'image': item.get('image', ''),
                        'product_url': item.get('url', ''),
                        'sku': item.get('sku', '')
                    }
                    if product_data['name']:
                        products.append(product_data)
        except Exception:
            continue
    
    # Microdata
    microdata_products = soup.find_all(attrs={'itemtype': re.compile(r'.*Product.*')})
    for product_elem in microdata_products:
        product_data = extract_from_microdata(product_elem, url)
        if product_data and product_data.get('name'):
            products.append(product_data)
    
    return products

def is_likely_product_element(element):
    """Détermine si un élément est probablement un produit"""
    # Vérifier la taille du contenu
    text_content = element.get_text(strip=True)
    if len(text_content) < 10 or len(text_content) > 2000:
        return False
    
    # Vérifier les caractéristiques d'un produit
    has_image = bool(element.find('img'))
    has_title = bool(element.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'b']))
    has_price = bool(re.search(r'[\d]+[.,\s]*\d*[.,\s]*\d+', text_content))
    has_link = bool(element.find('a', href=True))
    
    # Score de probabilité
    score = sum([has_image, has_title, has_price, has_link])
    
    return score >= 2  # Au moins 2 caractéristiques

def extract_product_data_from_element(element, url):
    """Extrait les données d'un élément produit identifié par sélecteur CSS"""
    product_data = {}
    
    # Nom du produit
    name = extract_product_name(element)
    if name:
        product_data['name'] = name
    
    # Prix
    price = extract_product_price(element)
    if price:
        product_data['price'] = price
    
    # Description
    description = extract_product_description(element)
    if description:
        product_data['description'] = description
    
    # Image
    image = extract_product_image(element, url)
    if image:
        product_data['image'] = image
    
    # Lien
    product_url = extract_product_url(element, url)
    if product_url:
        product_data['product_url'] = product_url
    
    # SKU
    sku = extract_product_sku(element)
    if sku:
        product_data['sku'] = sku
    
    return product_data

def extract_product_data_from_content(element, url):
    """Extrait les données d'un produit par analyse de contenu"""
    product_data = {}
    
    # Nom - chercher les titres et textes significatifs
    name_candidates = []
    
    # Titres
    titles = element.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    for title in titles:
        text = title.get_text(strip=True)
        if 3 <= len(text) <= 100:
            name_candidates.append(text)
    
    # Textes en gras/strong
    strong_texts = element.find_all(['strong', 'b'])
    for strong in strong_texts:
        text = strong.get_text(strip=True)
        if 5 <= len(text) <= 80:
            name_candidates.append(text)
    
    # Premier lien significatif
    links = element.find_all('a', href=True)
    for link in links:
        text = link.get_text(strip=True)
        if 5 <= len(text) <= 80 and not text.isdigit():
            name_candidates.append(text)
            break
    
    if name_candidates:
        product_data['name'] = name_candidates[0]
    
    # Prix - recherche avancée
    price = extract_price_advanced(element)
    if price:
        product_data['price'] = price
    
    # Image
    image = extract_product_image(element, url)
    if image:
        product_data['image'] = image
    
    # Lien
    product_url = extract_product_url(element, url)
    if product_url:
        product_data['product_url'] = product_url
    
    return product_data

def extract_product_name(element):
    """Extrait le nom du produit"""
    name_selectors = [
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        '.product-name', '.product-title', '.name', '.title',
        '.item-name', '.item-title', '.product__name', '.product-name-link',
        '.nom-produit', '.titre-produit', '.productName', '.product_name',
        '.card-title', '.product-card__title', '.product__title',
        '[data-product-name]', '[data-name]', '.elementor-heading-title'
    ]
    
    for selector in name_selectors:
        name_elem = element.select_one(selector)
        if name_elem:
            name = name_elem.get_text(strip=True)
            if name and 3 <= len(name) <= 200:
                return name
    
    return None

def extract_product_price(element):
    """Extrait le prix du produit"""
    price_selectors = [
        '.price', '.product-price', '.cost', '.amount', '.current-price',
        '.price-amount', '.woocommerce-Price-amount', '.regular-price',
        '.sale-price', '.special-price', '.prix', '.price-final',
        '.product-price', '.item-price', '.price__amount',
        '[class*="price"]', '[class*="prix"]', '.elementor-price'
    ]
    
    for selector in price_selectors:
        price_elem = element.select_one(selector)
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            # Nettoyer et valider le prix
            price_match = re.search(r'[\d]+[.,\s]*\d*[.,\s]*\d+', price_text)
            if price_match:
                return price_text.strip()
    
    return None

def extract_price_advanced(element):
    """Extraction avancée du prix par analyse de texte"""
    element_text = element.get_text()
    
    # Patterns de prix
    price_patterns = [
        r'(\d+[.,]\d{1,2})\s*€',
        r'€\s*(\d+[.,]\d{1,2})',
        r'(\d+[.,]\d{1,2})\s*\$',
        r'\$\s*(\d+[.,]\d{1,2})',
        r'(\d+)\s*euros?',
        r'(\d+)\s*dollars?',
        r'PRIX\s*:\s*[\'"]?(\d+[.,]\d{1,2})',
        r'price\s*:\s*[\'"]?(\d+[.,]\d{1,2})',
    ]
    
    for pattern in price_patterns:
        match = re.search(pattern, element_text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    
    # Recherche de nombres qui pourraient être des prix
    number_matches = re.findall(r'\b\d+[.,]\d{2}\b', element_text)
    if number_matches:
        # Prendre le premier nombre qui ressemble à un prix
        return number_matches[0]
    
    return None

def extract_product_description(element):
    """Extrait la description du produit"""
    desc_selectors = [
        '.description', '.product-description', '.desc', '.excerpt',
        '.product-desc', '.item-description', '.short-description',
        '.product-short-description', '.resume', '.product__description'
    ]
    
    for selector in desc_selectors:
        desc_elem = element.select_one(selector)
        if desc_elem:
            desc_text = desc_elem.get_text(strip=True)
            if desc_text:
                return desc_text[:500]
    
    return None

def extract_product_image(element, base_url):
    """Extrait l'image du produit"""
    img_selectors = [
        'img', '.product-image', '.image', '.item-image',
        '.product-img', '.product-thumbnail', '.thumbnail',
        '.product__image', '.card-img-top', '.product-image-img'
    ]
    
    for selector in img_selectors:
        img_elem = element.select_one(selector)
        if img_elem:
            src = img_elem.get('src') or img_elem.get('data-src') or img_elem.get('data-original')
            if src and not src.startswith('data:'):
                return urllib.parse.urljoin(base_url, src)
    
    return None

def extract_product_url(element, base_url):
    """Extrait l'URL du produit"""
    link_selectors = [
        'a', '.product-link', '.item-link', '.product-url',
        '.product-title-link', '.more-details', '.voir-produit'
    ]
    
    for selector in link_selectors:
        link_elem = element.select_one(selector)
        if link_elem and link_elem.get('href'):
            href = link_elem.get('href')
            if href and not href.startswith(('javascript:', '#')):
                return urllib.parse.urljoin(base_url, href)
    
    return None

def extract_product_sku(element):
    """Extrait le SKU du produit"""
    sku_selectors = [
        '.sku', '.product-id', '.reference', '.product-reference',
        '[data-sku]', '[data-product-id]', '[data-id]', '[data-reference]'
    ]
    
    for selector in sku_selectors:
        sku_elem = element.select_one(selector)
        if sku_elem:
            sku_text = sku_elem.get_text(strip=True)
            sku_data = (sku_elem.get('data-sku') or 
                       sku_elem.get('data-product-id') or 
                       sku_elem.get('data-id') or
                       sku_elem.get('data-reference'))
            return sku_text or sku_data
    
    return None

def extract_price_from_structured_data(data):
    """Extrait le prix des données structurées"""
    price = data.get('price') or data.get('offers', {}).get('price')
    if price:
        if isinstance(price, (int, float)):
            return f"{price} €"
        elif isinstance(price, str):
            price_match = re.search(r'(\d+[.,]\d{1,2})', price)
            if price_match:
                return f"{price_match.group(1)} €"
    return None

def extract_from_microdata(element, url):
    """Extrait les données depuis les microdatas"""
    product_data = {}
    
    # Nom
    name_elem = element.find(attrs={'itemprop': 'name'})
    if name_elem:
        product_data['name'] = name_elem.get_text(strip=True)
    
    # Prix
    price_elem = element.find(attrs={'itemprop': 'price'})
    if price_elem:
        product_data['price'] = price_elem.get_text(strip=True)
    
    # Image
    image_elem = element.find(attrs={'itemprop': 'image'})
    if image_elem and image_elem.get('src'):
        product_data['image'] = urllib.parse.urljoin(url, image_elem['src'])
    
    # URL
    url_elem = element.find(attrs={'itemprop': 'url'})
    if url_elem and url_elem.get('href'):
        product_data['product_url'] = urllib.parse.urljoin(url, url_elem['href'])
    
    return product_data

def deduplicate_products(products):
    """Déduplique les produits"""
    seen = set()
    unique_products = []
    
    for product in products:
        # Créer une clé unique
        name = product.get('name', '').lower().strip()
        url = product.get('product_url', '')
        price = product.get('price', '')
        
        key = f"{name}|{url}|{price}"
        
        if key not in seen and name:  # Ignorer les produits sans nom
            seen.add(key)
            unique_products.append(product)
    
    return unique_products

def extract_footer(html, url):
    """Extrait toutes les informations du footer"""
    soup = BeautifulSoup(html, "html.parser")
    footer_data = {}
    
    # Trouver le footer avec plus de sélecteurs
    footer_selectors = ['footer', '.footer', '#footer', '.site-footer', '.main-footer']
    footer = None
    for selector in footer_selectors:
        footer = soup.select_one(selector)
        if footer:
            break
    
    if footer:
        # Liens du footer
        footer_links = []
        for link in footer.find_all('a', href=True):
            link_text = link.get_text(strip=True)
            if link_text:  # Ignorer les liens sans texte
                footer_links.append({
                    'text': link_text,
                    'url': urllib.parse.urljoin(url, link['href'])
                })
        footer_data['links'] = footer_links
        
        # Texte du footer
        footer_text = footer.get_text(separator=' ', strip=True)
        footer_data['text'] = footer_text[:1000]  # Limiter la longueur
        
        # Informations de contact
        contact_info = {}
        
        # Extraire numéros de téléphone
        phones = re.findall(r'[\+]?[0-9\s\-\(\)]{10,}', footer_text)
        if phones:
            contact_info['phones'] = phones
        
        # Emails
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', footer_text)
        if emails:
            contact_info['emails'] = emails
            
        footer_data['contact_info'] = contact_info
    
    return footer_data


def extract_all_data(html, url):
    """Extrait toutes les données structurées d'une page - Version améliorée"""
    soup = BeautifulSoup(html, "html.parser")
    
    # Données de base avec plus de contexte
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_desc = ""
    m = soup.find("meta", attrs={"name":"description"})
    if m and m.get("content"):
        meta_desc = m["content"].strip()
    
    # Contenu textuel enrichi
    h1 = ""
    h1_tag = soup.find("h1")
    if h1_tag:
        h1 = h1_tag.get_text(separator=" ", strip=True)
    
    # Extraire tout le contenu textuel important
    content_text = []
    for tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li']:
        elements = soup.find_all(tag)
        for elem in elements:
            text = elem.get_text(separator=" ", strip=True)
            if text and len(text) > 10:
                content_text.append(text)
    
    excerpt = " | ".join(content_text)[:3000]  # Plus de contenu
    
    # Premier paragraphe (alternative à first_paragraph)
    first_paragraph = ""
    p_tag = soup.find('p')
    if p_tag:
        first_paragraph = p_tag.get_text(strip=True)[:500]
    
    # Images avec contexte
    images = []
    for img in soup.find_all('img', src=True):
        src = img.get('src') or img.get('data-src') or img.get('data-original')
        if src:
            alt = img.get('alt', '')
            images.append({
                'url': urllib.parse.urljoin(url, src),
                'alt': alt[:200] if alt else ''
            })
    
    # Métadonnées étendues
    meta_data = {}
    meta_tags = soup.find_all('meta')
    for meta in meta_tags:
        name = meta.get('name') or meta.get('property') or meta.get('itemprop')
        content = meta.get('content')
        if name and content:
            meta_data[name] = content
    
    # Extraire les produits avec catégorisation
    all_products = extract_products(html, url)
    promoted_products = []
    if url.endswith('/') or '/home' in url.lower() or url.count('/') <= 2:
        # C'est probablement la page d'accueil
        promoted_products = extract_promoted_products(html, url)
        print(f"🎯 Page d'accueil détectée: {len(promoted_products)} produits promus trouvés")
        
    # Marquer les produits promus
    for product in promoted_products:
        product['is_promoted'] = True
        product['promoted_on_homepage'] = True
        if not product.get('description'):
            product['description'] = f"PRODUIT PROMU - {product.get('name', '')}"
    
    # Pour les produits normaux, s'assurer qu'ils ne sont pas marqués comme promus
    for product in all_products:
        product['is_promoted'] = False
        product['promoted_on_homepage'] = False
    
    # Extraire les données structurées
    structured_data = extract_structured_data(soup, url)
    
    return {
        "url": url,
        "title": title,
        "meta_description": meta_desc,
        "h1": h1,
        "excerpt": excerpt,
        "first_paragraph": first_paragraph,  # Maintenant cette clé existe
        "content_text": content_text[:20],  # Garder les 20 premiers éléments
        "images": images[:15],  # Limiter mais garder plus d'images
        "meta_data": meta_data,
        "structured_data": structured_data,
        "products": all_products,
        "promoted_products": promoted_products,
        "footer": extract_footer(html, url),
        "word_count": len(soup.get_text().split()),
        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

def extract_structured_data(soup, url):
    """Extrait toutes les données structurées"""
    structured_data = []
    
    # JSON-LD
    script_tags = soup.find_all('script', type='application/ld+json')
    for script in script_tags:
        try:
            data = json.loads(script.string)
            structured_data.append(data)
        except Exception:
            pass
    
    # Microdata
    microdata = soup.find_all(attrs={'itemtype': True})
    for item in microdata:
        item_type = item.get('itemtype', '')
        if 'Product' in item_type or 'Offer' in item_type:
            try:
                name_elem = item.find(attrs={'itemprop': 'name'})
                price_elem = item.find(attrs={'itemprop': 'price'})
                
                microdata_obj = {
                    '@type': item_type,
                    'name': name_elem.get_text(strip=True) if name_elem else '',
                    'price': price_elem.get_text(strip=True) if price_elem else ''
                }
                structured_data.append(microdata_obj)
            except Exception:
                pass
    
    return structured_data

def merge_scraped_data():
    """Fusionne les données en séparant clairement produits normaux et produits promus"""
    try:
        # Charger last_scrape.json (produits normaux + données complètes)
        scrape_data = {}
        if os.path.exists("last_scrape.json"):
            with open("last_scrape.json", "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    scrape_data = json.loads(content)
                    if not isinstance(scrape_data, dict):
                        print("⚠️ last_scrape.json n'est pas un dictionnaire, réinitialisation")
                        scrape_data = {}
        
        # Charger last_promotions.json (uniquement produits promus)
        promo_data = {}
        if os.path.exists("last_promotions.json"):
            with open("last_promotions.json", "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    promo_data = json.loads(content)
                    if not isinstance(promo_data, dict):
                        print("⚠️ last_promotions.json n'est pas un dictionnaire, ignoré")
                        promo_data = {}
        
        # Structure finale fusionnée
        merged_data = scrape_data.copy()
        
        print(f"🔍 Fusion en cours: {len(scrape_data)} sites scrapés, {len(promo_data)} sites promotionnels")
        
        # Pour chaque site dans les promotions
        for site_id, promo_site_data in promo_data.items():
            if not isinstance(promo_site_data, dict):
                continue
                
            # Vérifier si le site existe déjà dans les données scrapées
            if site_id in merged_data:
                print(f"🔄 Fusion du site existant: {site_id}")
                
                # S'assurer que la structure est correcte
                if not isinstance(merged_data[site_id], dict):
                    merged_data[site_id] = {"results": []}
                
                if "results" not in merged_data[site_id]:
                    merged_data[site_id]["results"] = []
                
                # Récupérer les résultats promotionnels
                promo_results = promo_site_data.get("results", [])
                if not isinstance(promo_results, list):
                    promo_results = []
                
                # Pour chaque résultat promotionnel
                for promo_result in promo_results:
                    if not isinstance(promo_result, dict):
                        continue
                        
                    # Trouver le résultat correspondant dans les données scrapées (par URL)
                    promo_url = promo_result.get("url", "")
                    found_match = False
                    
                    for i, existing_result in enumerate(merged_data[site_id]["results"]):
                        if not isinstance(existing_result, dict):
                            continue
                            
                        existing_url = existing_result.get("url", "")
                        
                        # Si les URLs correspondent, ajouter les produits promus
                        if existing_url == promo_url or not existing_url:
                            print(f"  ✅ Ajout de {len(promo_result.get('promoted_products', []))} produits promus à la page {i}")
                            
                            # S'assurer que la clé promoted_products existe
                            if "promoted_products" not in existing_result:
                                existing_result["promoted_products"] = []
                            
                            # Ajouter les produits promus (remplacement complet)
                            existing_promoted = existing_result.get("promoted_products", [])
                            new_promoted = promo_result.get("promoted_products", [])
                            
                            # Fusionner et dédupliquer
                            all_promoted = existing_promoted + new_promoted
                            unique_promoted = []
                            seen = set()
                            
                            for product in all_promoted:
                                if not isinstance(product, dict):
                                    continue
                                key = f"{product.get('name', '').lower()}|{product.get('product_url', '')}"
                                if key not in seen:
                                    seen.add(key)
                                    unique_promoted.append(product)
                            
                            existing_result["promoted_products"] = unique_promoted
                            found_match = True
                            break
                    
                    # Si aucun match trouvé, ajouter comme nouveau résultat
                    if not found_match and promo_url:
                        print(f"  ➕ Nouvelle page ajoutée: {promo_url}")
                        merged_data[site_id]["results"].append(promo_result)
            
            else:
                # Nouveau site - l'ajouter complètement
                print(f"➕ Nouveau site ajouté: {site_id}")
                merged_data[site_id] = promo_site_data
        
        # Sauvegarder le résultat fusionné
        with open("last_scrape.json", "w", encoding="utf-8") as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=2)
        
        # Calculer les statistiques finales
        total_normal_products = 0
        total_promoted_products = 0
        total_sites = 0
        
        for site_id, site_data in merged_data.items():
            if isinstance(site_data, dict) and "results" in site_data:
                total_sites += 1
                for result in site_data["results"]:
                    if isinstance(result, dict):
                        total_normal_products += len(result.get("products", []))
                        total_promoted_products += len(result.get("promoted_products", []))
        
        print(f"✅ Fusion terminée: {total_sites} sites, {total_normal_products} produits normaux, {total_promoted_products} produits promus")
        
        return merged_data
        
    except Exception as e:
        print(f"❌ Erreur lors de la fusion: {e}")
        import traceback
        print(f"🔍 Détails: {traceback.format_exc()}")
        raise

def extract_links(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        norm = normalize_link(base_url, a["href"])
        if norm:
            links.add(norm)
    return list(links)

def fetch_with_requests(url):
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent":"Mozilla/5.0 (compatible; AutoScraper/1.0)"})
        resp.raise_for_status()
        return resp.text, None
    except Exception as e:
        return None, str(e)

def fetch_with_playwright(url, timeout_ms=PLAYWRIGHT_TIMEOUT):
    if not PLAYWRIGHT_AVAILABLE:
        return None, "Playwright non disponible"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, timeout=timeout_ms)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            html = page.content()
            browser.close()
            return html, None
    except PlaywrightTimeout as t:
        return None, f"Timeout Playwright: {t}"
    except Exception as e:
        return None, f"Erreur Playwright: {e}"

# Fonction pour calculer les statistiques
def calculate_statistics(results):
    """Calcule les statistiques des résultats"""
    total_pages = len(results)
    total_products = 0
    total_images = 0
    error_pages = 0
    
    for item in results:
        total_products += len(item.get('products', []))
        total_images += len(item.get('images', []))
        if item.get('error'):
            error_pages += 1
    
    return {
        'total_pages': total_pages,
        'total_products': total_products,
        'total_images': total_images,
        'error_pages': error_pages
    }

# Endpoint page principale
@app.route("/", methods=["GET"])
def index():
    return render_template("index5.html", playwright_available=PLAYWRIGHT_AVAILABLE)

# Endpoint de scraping (form POST)
@app.route("/scrape", methods=["POST"])
def scrape():
    start_url = request.form.get("start_url", "").strip()
    render_js = True if request.form.get("render_js") == "on" else False
    scrape_products = True if request.form.get("scrape_products") == "on" else False
    scrape_promoted_products = True if request.form.get("scrape_promoted_products") == "on" else False
    scrape_footer = True if request.form.get("scrape_footer") == "on" else False
    
    try:
        max_pages = int(request.form.get("max_pages") or DEFAULT_MAX_PAGES)
    except Exception:
        max_pages = DEFAULT_MAX_PAGES
    try:
        max_depth = int(request.form.get("max_depth") or DEFAULT_MAX_DEPTH)
    except Exception:
        max_depth = DEFAULT_MAX_DEPTH

    if not start_url:
        flash("URL de départ manquante.", "danger")
        return redirect(url_for("index"))

    # normaliser start_url
    parsed = urllib.parse.urlparse(start_url)
    if not parsed.scheme:
        start_url = "http://" + start_url
    start_url = start_url.rstrip("/")
    
     # Générer un site_id stable basé sur le domaine
    domain = urllib.parse.urlparse(start_url).netloc
    site_id = hashlib.md5(domain.encode("utf-8")).hexdigest()[:8]

    print(f"🕸️ Scraping du site {start_url} (site_id={site_id})")

    # BFS crawl
    visited = set()
    q = deque()
    q.append((start_url, 0))
    results = []

    while q and len(visited) < max_pages:
        url, depth = q.popleft()
        if url in visited:
            continue
        if depth > max_depth:
            continue
        if not same_domain(start_url, url):
            continue

        # marquer visité
        visited.add(url)

        # Récup HTML
        html = None
        error = None
        if render_js and PLAYWRIGHT_AVAILABLE:
            html, error = fetch_with_playwright(url)
            if html is None:
                html, error = fetch_with_requests(url)
        else:
            html, error = fetch_with_requests(url)
            if html is None and PLAYWRIGHT_AVAILABLE:
                html, error = fetch_with_playwright(url)

        if html:
            # Extraire toutes les données
            all_data = extract_all_data(html, url)
            
            # Si on ne veut pas les produits ou footer, les retirer
            if not scrape_products:
                all_data.pop('products', None)
            if not scrape_promoted_products:
                all_data.pop('promoted_products', None)
            else:
                # Logique pour détecter automatiquement les pages d'accueil
                current_url = all_data.get("url", "")
                is_likely_homepage = (
                    current_url.endswith('/') or 
                    '/home' in current_url.lower() or 
                    current_url.count('/') <= 2 or
                    depth == 0
                )
                all_data["is_homepage"] = is_likely_homepage
                
            if not scrape_footer:
                all_data.pop('footer', None)
                
            struct = all_data
            links = extract_links(html, url)
        else:
            struct = {
                "url": url,
                "title": "",
                "meta_description": "",
                "h1": "",
                "excerpt": "",
                "first_paragraph": "",
                "images": [],
                "meta_data": {},
                "structured_data": [],
                "products": [],
                "promoted_products": [],
                "footer": {},
                "word_count": 0,
                "is_homepage": False
            }
            links = []

        item = {
            "url": struct["url"],
            "title": struct["title"],
            "meta_description": struct["meta_description"],
            "h1": struct["h1"],
            "excerpt": struct["excerpt"],
            "first_paragraph": struct.get("first_paragraph",""),
            "images": struct.get("images", []),
            "meta_data": struct.get("meta_data", {}),
            "structured_data": struct.get("structured_data", []),
            "products": struct.get("products", []),
            "promoted_products": struct.get("promoted_products", []),
            "footer": struct.get("footer", {}),
            "word_count": struct.get("word_count", 0),
            "depth": depth,
            "error": error,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        results.append(item)

        # queue internal links
        for link in links:
            if len(visited) + len(q) >= max_pages:
                break
            if not same_domain(start_url, link):
                continue
            if link in visited:
                continue
            q.append((link.rstrip("/"), depth + 1))


    # Charger ancien contenu s'il existe
    temp_path = "last_scrape.json"
    data_all = {}
    if os.path.exists(temp_path):
        try:
            with open(temp_path, "r", encoding="utf-8") as f:
                data_all = json.load(f)
        except Exception as e:
            print("⚠️ Erreur de lecture du fichier JSON :", e)
            data_all = {}

    # Ajouter ou mettre à jour ce site
    data_all[site_id] = {
        "site_id": site_id,
        "start_url": start_url,
        "render_js_requested": render_js,
        "scrape_products": scrape_products,
        "scrape_promoted_products": scrape_promoted_products,  # ← AJOUTÉ
        "scrape_footer": scrape_footer,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "scraped_count": len(results),
        "results": results
    }

    # Réécrire tout le fichier
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data_all, f, ensure_ascii=False, indent=2)

    # Calculer les statistiques pour CE SITE uniquement
    stats = calculate_statistics(results)
    
    flash(f"✅ {len(results)} pages scrappées pour le site {start_url}.", "success")
    return render_template("index5.html",
                         results=results,
                         stats=stats,
                         playwright_available=PLAYWRIGHT_AVAILABLE,
                         current_site_id=site_id,
                         all_sites=data_all)
    
@app.route("/merge_data", methods=["POST"])
def merge_data():
    try:
        merged_data = merge_scraped_data()
        flash(f"Données fusionnées avec succès! {len(merged_data)} sites disponibles.", "success")
    except Exception as e:
        flash(f"Erreur lors de la fusion: {str(e)}", "danger")
    
    return redirect(url_for("index"))

# Téléchargement JSON
@app.route("/download_json", methods=["GET"])
def download_json():
    path = "last_scrape.json"
    if not os.path.exists(path):
        flash("Aucun résultat disponible. Lance un scraping d'abord.", "warning")
        return redirect(url_for("index"))
    return send_file(path, as_attachment=True, download_name="data.json", mimetype="application/json")

@app.route("/init_rag_manual", methods=["POST"])
def init_rag_manual():
    """Initialise manuellement le RAG seulement si l'utilisateur le demande"""
    if not MISTRAL_API_KEY:
        flash("Clé API Mistral non configurée.", "danger")
        return redirect(url_for("ask_question"))
    
    try:
        rag_system = get_rag_system(MISTRAL_API_KEY)
        
        # Vérifier d'abord s'il y a des changements
        changes = rag_system.check_data_changes()
        
        if not changes['has_changes'] and rag_system.is_initialized:
            flash("✅ RAG déjà à jour - Pas de changement détecté", "info")
            return redirect(url_for("ask_question"))
        
        # Initialiser manuellement - UTILISER load_scraped_data() au lieu de initialize_rag()
        success = rag_system.load_scraped_data()  # ← CHANGEMENT ICI
        
        if success:
            stats = rag_system.get_stats()
            message = (f"🎉 RAG initialisé manuellement!\n"
                      f"📊 {stats['total_sites']} sites, {stats['total_pages']} pages, "
                      f"{stats['total_products']} produits, {stats['total_documents']} documents")
            flash(message, "success")
        else:
            flash("❌ Échec de l'initialisation du RAG", "danger")
            
    except FileNotFoundError:
        flash("❌ Fichier last_scrape.json non trouvé. Effectuez d'abord un scraping.", "danger")
    except Exception as e:
        flash(f"❌ Erreur lors de l'initialisation: {str(e)}", "danger")
    
    return redirect(url_for("ask_question"))

@app.route("/init_rag_force", methods=["POST"])
def init_rag_force():
    """Force la réinitialisation complète du RAG"""
    if not MISTRAL_API_KEY:
        flash("Clé API Mistral non configurée. Configurez la variable MISTRAL_API_KEY.", "danger")
        return redirect(url_for("index"))
    
    success, message = initialize_rag_system(MISTRAL_API_KEY, force_reload=True)
    
    if success:
        flash(message, "success")
    else:
        flash(message, "danger")
    
    return redirect(url_for("ask_question"))


# Téléchargement CSV
@app.route("/download_csv", methods=["GET"])
def download_csv():
    path = "last_scrape.json"
    if not os.path.exists(path):
        flash("Aucun résultat disponible. Lance un scraping d'abord.", "warning")
        return redirect(url_for("index"))
    
    with open(path, "r", encoding="utf-8") as f:
        data_all = json.load(f)

    all_results = []
    for site_id, site_data in data_all.items():
        results = site_data.get("results", [])
        for r in results:
            r["site_id"] = site_id
            r["site_url"] = site_data.get("start_url", "")
            all_results.append(r)

    # Générer CSV en mémoire
    out = io.StringIO()
    writer = csv.writer(out)

    # En-tête étendu
    header = [
        "site_id", "site_url", "url", "title", "meta_description", "h1", 
        "first_paragraph", "excerpt", "word_count", "images_count", 
        "products_count", "footer_links_count", "depth", "error", "fetched_at"
    ]
    writer.writerow(header)

    for r in all_results:
        writer.writerow([
            r.get("site_id", ""),
            r.get("site_url", ""),
            r.get("url", ""),
            r.get("title", ""),
            r.get("meta_description", ""),
            r.get("h1", ""),
            r.get("first_paragraph", ""),
            r.get("excerpt", ""),
            r.get("word_count", 0),
            len(r.get("images", [])),
            len(r.get("products", [])),
            len(r.get("footer", {}).get("links", [])),
            r.get("depth", ""),
            r.get("error", ""),
            r.get("fetched_at", "")
        ])

    mem = io.BytesIO()
    mem.write(out.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="data.csv", mimetype="text/csv; charset=utf-8")


# Téléchargement produits CSV
@app.route("/download_products_csv", methods=["GET"])
def download_products_csv():
    path = "last_scrape.json"
    if not os.path.exists(path):
        flash("Aucun résultat disponible. Lance un scraping d'abord.", "warning")
        return redirect(url_for("index"))
    
    with open(path, "r", encoding="utf-8") as f:
        data_all = json.load(f)

    all_products = []
    for site_id, site_data in data_all.items():
        results = site_data.get("results", [])
        for page in results:
            for product in page.get("products", []):
                product["site_id"] = site_id
                product["site_url"] = site_data.get("start_url", "")
                product["page_url"] = page.get("url", "")
                all_products.append(product)

    # Générer CSV produits
    out = io.StringIO()
    writer = csv.writer(out)
    
    header = ["site_id", "site_url", "page_url", "name", "price", "description", "image", "product_url", "sku"]
    writer.writerow(header)
    
    for product in all_products:
        writer.writerow([
            product.get("site_id", ""),
            product.get("site_url", ""),
            product.get("page_url", ""),
            product.get("name", ""),
            product.get("price", ""),
            product.get("description", ""),
            product.get("image", ""),
            product.get("product_url", ""),
            product.get("sku", "")
        ])
    
    mem = io.BytesIO()
    mem.write(out.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="products.csv", mimetype="text/csv; charset=utf-8")

@app.route("/check_rag_changes")
def check_rag_changes():
    """Vérifie si des changements sont détectés sans initialiser"""
    if not MISTRAL_API_KEY:
        return {"error": "Clé API non configurée"}, 400
    
    try:
        rag_system = get_rag_system(MISTRAL_API_KEY)
        stats = rag_system.get_stats()
        
        # Méthode simplifiée pour détecter les changements
        file_path = "last_scrape.json"
        has_changes = False
        reason = "unknown"
        
        if not os.path.exists(file_path):
            has_changes = True
            reason = "file_not_found"
        elif not stats.get('initialized', False):
            has_changes = True
            reason = "not_initialized"
        else:
            # Vérifier si le fichier a été modifié récemment
            file_mtime = os.path.getmtime(file_path)
            # Si le fichier a été modifié dans les dernières 24h, considérer qu'il y a des changements
            if time.time() - file_mtime < 86400:  # 24 heures
                has_changes = True
                reason = "recent_changes"
            else:
                has_changes = False
                reason = "no_changes"
        
        return {
            "has_changes": has_changes,
            "is_initialized": stats.get('initialized', False),
            "reason": reason,
            "can_answer_questions": stats.get('initialized', False)
        }
    except Exception as e:
        return {"error": str(e)}, 500



# Route de compatibilité
@app.route("/init_rag", methods=["GET", "POST"])
def init_rag():
    """Route de compatibilité"""
    if request.method == "GET":
        return redirect(url_for("ask_question"))
    
    if not MISTRAL_API_KEY:
        flash("Clé API Mistral non configurée.", "danger")
        return redirect(url_for("ask_question"))
    
    try:
        rag_system = get_rag_system(MISTRAL_API_KEY)
        rag_system.load_scraped_data()
        stats = rag_system.get_stats()
        
        if stats['initialized']:
            message = (f"✅ RAG initialisé - {stats['total_sites']} sites, "
                      f"{stats['total_pages']} pages, {stats['total_products']} produits")
            flash(message, "success")
        else:
            flash("❌ Échec initialisation du RAG", "danger")
            
    except Exception as e:
        flash(f"❌ Erreur: {str(e)}", "danger")
    
    return redirect(url_for("ask_question"))


@app.route("/ask", methods=["GET", "POST"])
def ask_question():
    """Pose une question au système RAG"""
    rag_initialized = False
    rag_stats = {}
    
    try:
        if MISTRAL_API_KEY:
            rag_system = get_rag_system(MISTRAL_API_KEY)
            rag_stats = rag_system.get_stats()
            rag_initialized = rag_stats.get('initialized', False)
    except Exception as e:
        print(f"Erreur RAG: {e}")
    
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        
        if not question:
            flash("Veuillez poser une question.", "warning")
            return redirect(url_for("ask_question"))
        
        if not MISTRAL_API_KEY:
            flash("Clé API Mistral non configurée.", "danger")
            return redirect(url_for("ask_question"))
        
        if not rag_initialized:
            flash("Système RAG non initialisé. Veuillez d'abord initialiser.", "warning")
            return redirect(url_for("ask_question"))
        
        try:
            rag_system = get_rag_system(MISTRAL_API_KEY)
            answer = rag_system.ask_question(question)
            
            return render_template("ask.html", 
                                question=question, 
                                answer=answer,
                                rag_initialized=rag_initialized,
                                rag_stats=rag_stats)
            
        except Exception as e:
            flash(f"Erreur: {str(e)}", "danger")
            return redirect(url_for("ask_question"))
    
    return render_template("ask.html", 
                          rag_initialized=rag_initialized,
                          rag_stats=rag_stats)
    
@app.route("/rag_search", methods=["POST"])
def rag_search():
    """Endpoint pour rechercher dans le RAG sans génération LLM"""
    if not MISTRAL_API_KEY:
        return {"error": "Clé API Mistral non configurée"}, 400
    
    try:
        rag_system = get_rag_system(MISTRAL_API_KEY)
        stats = rag_system.get_stats()
        
        if not stats.get('initialized', False):
            return {"error": "Système RAG non initialisé"}, 400
        
        query = request.json.get("query", "").strip()
        k = request.json.get("k", 10)
        
        if not query:
            return {"error": "Query manquante"}, 400
        
        # Recherche avec FAISS
        results = rag_system.search(query, k=k)
        
        # Formater les résultats
        formatted_results = []
        for result in results:
            formatted_results.append({
                "document": result['document'],
                "score": result['score'],
                "metadata": result['metadata']
            })
        
        return {
            "query": query,
            "results_count": len(formatted_results),
            "results": formatted_results
        }
        
    except Exception as e:
        return {"error": str(e)}, 500




@app.route("/rag_status")
def rag_status():
    """Retourne le statut détaillé du système RAG"""
    try:
        if not MISTRAL_API_KEY:
            return {"status": "no_api_key"}
        
        rag_system = get_rag_system(MISTRAL_API_KEY)
        stats = rag_system.get_stats()
        
        is_up_to_date = rag_system.is_up_to_date() if hasattr(rag_system, 'is_up_to_date') else False
        
        return {
            "status": "initialized" if stats.get('initialized', False) else "not_initialized",
            "up_to_date": is_up_to_date,
            "total_documents": stats.get('total_documents', 0),
            "total_products": stats.get('total_products', 0),
            "total_pages": stats.get('total_pages', 0),
            "total_sites": stats.get('total_sites', 0),
            "index_size": stats.get('index_size', 0),
            "data_hash": rag_system.data_hash if hasattr(rag_system, 'data_hash') else None
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.route("/rebuild_index", methods=["POST"])
def rebuild_index():
    """Reconstruit l'index FAISS"""
    if not MISTRAL_API_KEY:
        flash("Clé API Mistral non configurée.", "danger")
        return redirect(url_for("index"))
    
    try:
        rag_system = get_rag_system(MISTRAL_API_KEY)
        
        # Recharger les données et reconstruire l'index
        rag_system.load_scraped_data()
        
        stats = rag_system.get_stats()
        flash(f"Index FAISS reconstruit avec succès! {stats['index_size']} vecteurs indexés.", "success")
        
    except Exception as e:
        flash(f"Erreur lors de la reconstruction: {str(e)}", "danger")
    
    return redirect(url_for("ask_question"))

@app.route("/save_index", methods=["POST"])
def save_index():
    """Sauvegarde l'index FAISS sur disque"""
    if not MISTRAL_API_KEY:
        return {"error": "Clé API non configurée"}, 400
    
    try:
        import faiss
        rag_system = get_rag_system(MISTRAL_API_KEY)
        
        if rag_system.index is None:
            return {"error": "Aucun index à sauvegarder"}, 400
        
        # Sauvegarder l'index FAISS
        faiss.write_index(rag_system.index, "faiss_index.bin")
        
        # Sauvegarder les métadonnées
        with open("faiss_metadata.json", "w", encoding="utf-8") as f:
            json.dump({
                "documents": rag_system.documents,
                "metadata": rag_system.metadata
            }, f, ensure_ascii=False, indent=2)
        
        flash("Index FAISS sauvegardé avec succès!", "success")
        return {"status": "success", "index_size": rag_system.index.ntotal}
        
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/rag_debug")
def rag_debug():
    """Debug du système RAG"""
    if not MISTRAL_API_KEY:
        flash("Clé API Mistral non configurée.", "danger")
        return redirect(url_for("ask_question"))
    
    try:
        rag_system = get_rag_system(MISTRAL_API_KEY)
        
        # Vérifier si la méthode debug_indexation existe
        if hasattr(rag_system, 'debug_indexation'):
            rag_system.debug_indexation()
        
        stats = rag_system.get_stats()
        
        return render_template("rag_debug.html", 
                             stats=stats,
                             rag_initialized=stats.get('initialized', False))
        
    except Exception as e:
        flash(f"Erreur lors du debug: {str(e)}", "danger")
        return redirect(url_for("ask_question"))
    

@app.route("/load_index", methods=["POST"])
def load_index():
    """Charge l'index FAISS depuis le disque"""
    if not MISTRAL_API_KEY:
        flash("Clé API Mistral non configurée.", "danger")
        return redirect(url_for("index"))
    
    try:
        import faiss
        rag_system = get_rag_system(MISTRAL_API_KEY)
        
        if not os.path.exists("faiss_index.bin") or not os.path.exists("faiss_metadata.json"):
            flash("Aucun index sauvegardé trouvé. Initialisez d'abord le RAG.", "warning")
            return redirect(url_for("ask_question"))
        
        # Charger l'index FAISS
        rag_system.index = faiss.read_index("faiss_index.bin")
        
        # Charger les métadonnées
        with open("faiss_metadata.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            rag_system.documents = data["documents"]
            rag_system.metadata = data["metadata"]
        
        # Charger raw_data si nécessaire
        if os.path.exists("last_scrape.json"):
            with open("last_scrape.json", "r", encoding="utf-8") as f:
                rag_system.raw_data = json.load(f)
        
        flash(f"Index FAISS chargé avec succès! {rag_system.index.ntotal} vecteurs.", "success")
        
    except Exception as e:
        flash(f"Erreur lors du chargement: {str(e)}", "danger")
    
    return redirect(url_for("ask_question"))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)