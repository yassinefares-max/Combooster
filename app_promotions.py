# app_promotions.py
import os
import io
import csv
import json
import time
import re
import urllib.parse
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from bs4 import BeautifulSoup
import requests
import hashlib
from rag_system import initialize_rag_system, get_rag_system

# Playwright optionnel (sync)
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change_me_promotions")

# ================================
# INITIALISATION DU RAG
# ================================
rag = None

def init_rag():
    """Initialise le système RAG après scraping."""
    global rag
    print("📄 Initialisation du système RAG avec les derniers produits...")

    api_key = os.getenv("MISTRAL_API_KEY", None)
    if not api_key:
        print("⚠️ Aucune clé MISTRAL_API_KEY détectée — utilisation du mode local TF-IDF uniquement.")

    try:
        rag_instance = get_rag_system(api_key)
        rag_instance.load_scraped_data("last_promotions.json")
        rag = rag_instance
        print("✅ RAG initialisé avec succès à partir de last_promotions.json.")
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation du RAG : {e}")
        rag = None

# Initialiser au démarrage si le fichier existe
if os.path.exists("last_promotions.json"):
    init_rag()

# ================================
# PARAMÈTRES GÉNÉRAUX
# ================================
REQUEST_TIMEOUT = 20
PLAYWRIGHT_TIMEOUT = 30000

# ---------- UTILITAIRES ----------
def normalize_link(base, link):
    if not link:
        return None
    link = link.split('#')[0].strip()
    if link.startswith("javascript:") or link.startswith("mailto:"):
        return None
    return urllib.parse.urljoin(base, link)

def fetch_with_requests(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        resp = requests.get(url, timeout=30, headers=headers)
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

# ---------- PARAMÈTRES SCRAPING ----------
PRODUCT_SELECTORS = [
    # Sélecteurs essentiels seulement
    '.product', '.product-item', '.product-card', 
    '.product-block', '.product-miniature', '.product-wrapper',
    '.woocommerce-product', '.grid-product', '.product-content',
    '[data-product]', '.item-product', '.shop-item',
    '.produit', '.article', '.card'
]

# Sélecteurs pour identifier et EXCLURE les sections non-produits
NON_PRODUCT_SELECTORS = [
    'header', 'footer', 'nav', '.header', '.footer', '.nav', '.navigation',
    '.blog', '.blog-post', '.article', '.news', '.actualites', '.actualite',
    '.contact', '.contact-us', '.contactez-nous', '.nous-contacter',
    '.about', '.about-us', '.a-propos', '.equipe', '.team',
    '.faq', '.help', '.aide', '.support',
    '.login', '.register', '.connexion', '.inscription',
    '.cart', '.panier', '.basket', '.checkout', '.paiement',
    '.account', '.compte', '.mon-compte',
    '.sidebar', '.widget', '.menu', '.breadcrumb',
    '.testimonial', '.temoignage', '.review', '.avis',
    '.social', '.social-media', '.reseaux-sociaux',
    '.newsletter', '.subscription', '.abonnement',
    '.policy', '.privacy', '.confidentialite', '.mentions-legales',
    '.legal', '.cgv', '.conditions'
]

# Mots-clés pour identifier le contenu non-produit
NON_PRODUCT_KEYWORDS = [
    'blog', 'article', 'actualité', 'news', 'nouvelle',
    'contact', 'nous contacter', 'écrivez-nous', 'tel:', 'tél:', 'email', 'e-mail',
    'à propos', 'about', 'équipe', 'team', 'histoire', 'mission',
    'faq', 'aide', 'support', 'comment', 'guide',
    'connexion', 'login', 'inscription', 'register', 'compte', 'account',
    'panier', 'cart', 'commande', 'order', 'paiement', 'payment',
    'livraison', 'delivery', 'shipping', 'frais de port',
    'mentions légales', 'confidentialité', 'politique', 'conditions', 'cgv',
    'témoignage', 'avis client', 'review', 'rating'
]

PRICE_REGEX = re.compile(
    r'(?:(?:\d{1,3}(?:[.,\s]\d{3})*)(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*'
    r'(?:€|eur|euros|\$|usd|USD|dollar|\£|GBP|livre|'
    r'DT|dt|dinar|TND|tnd|دينار|دت|'
    r'دج|DA|da|دينار جزائري|'
    r'درهم|DH|dh|MAD|mad|'
    r'ريال|Rial|ريال سعودي)?', 
    re.IGNORECASE
)

# ================================
# FONCTIONS D'EXTRACTION
# ================================
def extract_text(elem):
    return elem.get_text(" ", strip=True) if elem else ""

def extract_image(elem, base_url):
    """Extrait l'URL de l'image - version améliorée"""
    # Méthode 1: Balise img directe avec priorité sur les bonnes classes
    priority_selectors = ['.product-image', '.product-img', '.main-image', '[data-image]', 'img[src]']
    
    for selector in priority_selectors:
        imgs = elem.select(selector)
        for img in imgs:
            for attr in ['src', 'data-src', 'data-original', 'data-lazy-src', 'data-lazy', 'data-image']:
                src = img.get(attr)
                if src and not src.startswith('data:') and len(src) > 10:  # Éviter les URLs trop courtes
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = urllib.parse.urljoin(base_url, src)
                    elif not src.startswith('http'):
                        src = urllib.parse.urljoin(base_url, src)
                    return src
    
    # Méthode 2: Toutes les balises img dans l'élément
    imgs = elem.select('img')
    for img in imgs:
        for attr in ['src', 'data-src', 'data-original', 'data-lazy-src', 'data-lazy']:
            src = img.get(attr)
            if src and not src.startswith('data:') and len(src) > 10:
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = urllib.parse.urljoin(base_url, src)
                elif not src.startswith('http'):
                    src = urllib.parse.urljoin(base_url, src)
                return src
    
    # Méthode 3: Style background-image
    style = elem.get('style', '')
    if 'url(' in style:
        matches = re.findall(r'url\(([^)]+)\)', style)
        for url in matches:
            url = url.strip(' "\'')
            if url and not url.startswith('data:') and len(url) > 10:
                return urllib.parse.urljoin(base_url, url)
    
    return ""

def extract_name(elem):
    for sel in ['h1','h2','h3','h4','.product-title','.title','.name','.product-name','.card-title','a']:
        t = elem.select_one(sel)
        if t:
            txt = extract_text(t)
            if 3 <= len(txt) <= 200:
                return txt
    strong = elem.find(['strong','b'])
    if strong:
        txt = extract_text(strong)
        if 3 <= len(txt) <= 200:
            return txt
    txt = extract_text(elem).split('\n')[0].strip()
    return txt if len(txt) >= 3 else None

def extract_price(elem):
    """Extrait le prix depuis un élément HTML ou retourne 'Indisponible'"""
    # D'abord vérifier les indicateurs d'indisponibilité
    elem_text = extract_text(elem).lower()
    unavailable_indicators = [
        'indisponible', 'out of stock', 'en rupture', 'rupture', 
        'stock épuisé', 'épuisé', 'non disponible', 'sold out',
        'coming soon', 'bientôt disponible', 'availability out'
    ]
    
    for indicator in unavailable_indicators:
        if indicator in elem_text:
            return "Indisponible"
    
    # Vérifier aussi dans les classes CSS
    elem_classes = ' '.join(elem.get('class', [])).lower()
    for indicator in unavailable_indicators:
        if indicator in elem_classes:
            return "Indisponible"
    
    # Maintenant chercher le prix
    txt = extract_text(elem)
    
    # Chercher d'abord dans les sélecteurs de prix spécifiques
    price_text = None
    for sel in ['.price', '.prix', '.sale-price', '.old-price', '.current-price', '.regular-price', '.product-price', '[class*="price"]']:
        pe = elem.select_one(sel)
        if pe:
            t = extract_text(pe)
            m = PRICE_REGEX.search(t)
            if m:
                price_text = m.group(0).strip()
                break
    
    # Si pas trouvé, chercher dans tout l'élément
    if not price_text:
        m = PRICE_REGEX.search(txt)
        if m:
            price_text = m.group(0).strip()
    
    # Filtrer les faux positifs (prix trop courts ou invalides)
    if price_text:
        # Nettoyer le prix
        price_clean = re.sub(r'[^\d.,]', '', price_text)
        
        # Vérifier si c'est un prix valide (au moins 2 caractères et contient des chiffres)
        if len(price_clean) < 2 or not any(c.isdigit() for c in price_clean):
            price_text = None
        # Vérifier les prix trop bas (moins de 0.5)
        elif re.match(r'^[01][.,]?\d*$', price_clean) and float(price_clean.replace(',', '.')) < 0.5:
            price_text = None
    
    if not price_text:
        return "Prix non spécifié"
    
    return price_text

def extract_description(elem):
    for sel in ['.description','.desc','.product-desc','.short-desc','.excerpt','.summary']:
        d = elem.select_one(sel)
        if d:
            return extract_text(d)[:500]
    p = elem.find('p')
    if p:
        return extract_text(p)[:500]
    return None

def extract_product_url(elem, base_url):
    a = elem.select_one('a[href]')
    if a:
        href = a.get('href')
        if href and not href.startswith('javascript:'):
            return urllib.parse.urljoin(base_url, href)
    return None

def is_non_product_section(elem):
    """Vérifie si un élément fait partie d'une section non-produit"""
    # Vérifier les sélecteurs CSS
    for selector in NON_PRODUCT_SELECTORS:
        if elem.select(selector):
            return True
    
    # Vérifier les classes et IDs
    elem_classes = ' '.join(elem.get('class', []))
    elem_id = elem.get('id', '')
    elem_text = extract_text(elem).lower()
    
    non_product_indicators = NON_PRODUCT_SELECTORS + NON_PRODUCT_KEYWORDS
    
    for indicator in non_product_indicators:
        if (indicator in elem_classes.lower() or 
            indicator in elem_id.lower() or 
            indicator in elem_text):
            return True
    
    # Vérifier le texte pour les mots-clés non-produit
    for keyword in NON_PRODUCT_KEYWORDS:
        if keyword in elem_text:
            return True
    
    return False

# ================================
# SCRAPING HOMEPAGE - VERSION PRODUITS SEULEMENT
# ================================
def extract_promoted_from_homepage(html, base_url):
    """Extrait uniquement les produits avec URL, image, prix et description"""
    soup = BeautifulSoup(html, "html.parser")
    found_products = []
    
    print(f"\n{'='*60}")
    print(f"EXTRACTION PRODUITS SIMPLIFIÉE pour {base_url}")
    print(f"{'='*60}")

    # APPROCHE DIRECTE: Chercher les éléments qui ressemblent à des produits
    all_candidates = []
    
    # 1. Sélecteurs produits standards
    for psel in PRODUCT_SELECTORS:
        try:
            found = soup.select(psel)
            all_candidates.extend(found)
        except Exception:
            continue
    
    # 2. Éléments avec structure de produit
    if len(all_candidates) < 5:
        potential_elements = soup.find_all(['div', 'article', 'li', 'section'])
        for elem in potential_elements:
            if has_product_structure(elem):
                all_candidates.append(elem)
    
    print(f"Candidats trouvés: {len(all_candidates)}")
    
    # Extraction SIMPLIFIÉE
    for cand in all_candidates:
        try:
            # NOM
            name = extract_simple_name(cand)
            if not name or len(name) < 3:
                continue
            
            # PRIX
            price = extract_simple_price(cand)
            
            # IMAGE
            image = extract_simple_image(cand, base_url)
            
            # URL PRODUIT
            product_url = extract_simple_product_url(cand, base_url)
            
            # DESCRIPTION
            description = extract_simple_description(cand)
            
            # Créer le produit uniquement avec les 4 champs demandés
            product = {
                'name': name,
                'price': price or "Prix non spécifié",
                'image': image or "",
                'product_url': product_url or base_url
                # PAS de sku, pas d'autres champs
            }
            
            found_products.append(product)
                
        except Exception as e:
            continue
    
    # Dédupliquer
    unique = []
    seen = set()
    for p in found_products:
        key = f"{p['name'].lower().strip()}|{p['product_url']}"
        if key not in seen:
            seen.add(key)
            unique.append(p)
    
    print(f"✅ {len(unique)} produits extraits (nom, prix, image, URL)")
    print(f"{'='*60}\n")
    
    return unique

def has_product_structure(element):
    """Vérifie rapidement si un élément a une structure de produit"""
    text = element.get_text(strip=True)
    if len(text) < 10:
        return False
    
    has_image = bool(element.find('img'))
    has_link = bool(element.find('a', href=True))
    
    return has_image and has_link

def extract_simple_name(element):
    """Extrait le nom du produit simplement"""
    # Chercher dans les titres
    for tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        title = element.find(tag)
        if title:
            name = title.get_text(strip=True)
            if 3 <= len(name) <= 150:
                return name
    
    # Chercher dans les liens
    first_link = element.find('a')
    if first_link:
        link_text = first_link.get_text(strip=True)
        if 5 <= len(link_text) <= 100 and not link_text.isdigit():
            return link_text
    
    # Premier texte significatif
    text = element.get_text(strip=True)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    for line in lines:
        if 5 <= len(line) <= 100 and not line.isdigit():
            return line
    
    return None

def extract_simple_price(element):
    """Extrait le prix simplement"""
    text = element.get_text()
    
    # Chercher dans les sélecteurs de prix
    price_selectors = ['.price', '.prix', '.amount', '.current-price', '.product-price']
    for selector in price_selectors:
        price_elem = element.select_one(selector)
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            price_match = PRICE_REGEX.search(price_text)
            if price_match:
                return price_match.group(0).strip()
    
    # Chercher par regex dans tout l'élément
    price_match = PRICE_REGEX.search(text)
    if price_match:
        return price_match.group(0).strip()
    
    return "Prix non spécifié"

def extract_simple_image(element, base_url):
    """Extrait l'image simplement"""
    img = element.find('img')
    if img:
        for attr in ['src', 'data-src', 'data-original', 'data-lazy-src']:
            src = img.get(attr)
            if src and not src.startswith('data:'):
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = urllib.parse.urljoin(base_url, src)
                elif not src.startswith('http'):
                    src = urllib.parse.urljoin(base_url, src)
                return src
    return ""

def extract_simple_product_url(element, base_url):
    """Extrait l'URL du produit simplement"""
    link = element.find('a', href=True)
    if link:
        href = link.get('href')
        if href and not href.startswith(('javascript:', '#')):
            return urllib.parse.urljoin(base_url, href)
    return ""

def extract_simple_description(element):
    """Extrait la description simplement"""
    # Chercher dans les sélecteurs de description
    desc_selectors = ['.description', '.desc', '.product-desc', '.excerpt']
    for selector in desc_selectors:
        desc_elem = element.select_one(selector)
        if desc_elem:
            desc = desc_elem.get_text(strip=True)
            if desc:
                return desc[:300]  # Limiter à 300 caractères
    
    # Chercher le premier paragraphe
    first_p = element.find('p')
    if first_p:
        desc = first_p.get_text(strip=True)
        if desc:
            return desc[:300]
    
    return ""


def has_product_characteristics(element):
    """Vérifie si un élément a des caractéristiques de produit"""
    text = extract_text(element)
    if len(text) < 20 or len(text) > 2000:
        return False
    
    # Vérifier la présence d'image
    has_img = bool(element.find('img'))
    
    # Vérifier la présence de titre/texte significatif
    has_title = bool(element.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'b']))
    
    # Vérifier la présence de prix
    has_price = bool(re.search(r'[\d]+[.,\s]*\d*[.,\s]*\d+', text))
    
    # Vérifier la présence de lien
    has_link = bool(element.find('a', href=True))
    
    # Score de probabilité
    score = sum([has_img, has_title, has_price, has_link])
    return score >= 2

def extract_product_name_advanced(element):
    """Extraction avancée du nom du produit"""
    # Priorité 1: Sélecteurs spécifiques
    name_selectors = [
        '.product-name', '.product-title', '.item-name', '.title', 
        'h1', 'h2', 'h3', 'h4', '[data-product-name]', '[data-name]',
        '.name', '.nom-produit', '.product__name', '.card-title',
        '.woocommerce-loop-product__title', '.product-item__name'
    ]
    
    for selector in name_selectors:
        name_elem = element.select_one(selector)
        if name_elem:
            name = extract_text(name_elem)
            if 3 <= len(name) <= 200:
                return name
    
    # Priorité 2: Texte du premier lien
    first_link = element.select_one('a[href]')
    if first_link:
        link_text = extract_text(first_link)
        if 5 <= len(link_text) <= 100 and not link_text.isdigit():
            return link_text
    
    # Priorité 3: Texte en gras/strong
    strong_elem = element.find(['strong', 'b'])
    if strong_elem:
        strong_text = extract_text(strong_elem)
        if 5 <= len(strong_text) <= 100:
            return strong_text
    
    # Priorité 4: Premier texte significatif
    text = extract_text(element)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    for line in lines:
        if 5 <= len(line) <= 100 and not line.isdigit():
            return line
    
    return None

def extract_price_advanced(element):
    """Extraction avancée du prix"""
    # D'abord vérifier les indicateurs d'indisponibilité
    elem_text = extract_text(element).lower()
    unavailable_indicators = [
        'indisponible', 'out of stock', 'en rupture', 'rupture', 
        'stock épuisé', 'épuisé', 'non disponible', 'sold out',
        'coming soon', 'bientôt disponible', 'availability out'
    ]
    
    for indicator in unavailable_indicators:
        if indicator in elem_text:
            return "Indisponible"
    
    # Chercher dans les sélecteurs de prix
    price_selectors = [
        '.price', '.product-price', '.current-price', '.regular-price',
        '.sale-price', '.prix', '.amount', '.woocommerce-Price-amount',
        '[class*="price"]', '[data-price]', '.price__amount'
    ]
    
    for selector in price_selectors:
        price_elem = element.select_one(selector)
        if price_elem:
            price_text = extract_text(price_elem)
            price_match = PRICE_REGEX.search(price_text)
            if price_match:
                return price_match.group(0).strip()
    
    # Recherche par regex dans tout l'élément
    element_html = str(element)
    price_matches = PRICE_REGEX.findall(element_html)
    if price_matches:
        # Prendre le premier prix qui semble valide
        for match in price_matches:
            clean_price = re.sub(r'[^\d.,]', '', match)
            if len(clean_price) >= 2 and any(c.isdigit() for c in clean_price):
                return match.strip()
    
    return "Prix non spécifié"

def extract_image_advanced(element, base_url):
    """Extraction avancée de l'image"""
    # Chercher dans toutes les balises img
    imgs = element.find_all('img')
    for img in imgs:
        # Essayer tous les attributs possibles
        for attr in ['src', 'data-src', 'data-original', 'data-lazy-src', 
                    'data-lazy', 'data-image', 'srcset']:
            src = img.get(attr)
            if src and not src.startswith('data:'):
                # Nettoyer l'URL
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = urllib.parse.urljoin(base_url, src)
                elif not src.startswith('http'):
                    src = urllib.parse.urljoin(base_url, src)
                
                # Vérifier que c'est une URL valide
                if len(src) > 10 and '.' in src:
                    return src
    
    # Chercher dans les styles background-image
    style = element.get('style', '')
    if 'background-image' in style:
        matches = re.findall(r'url\(([^)]+)\)', style)
        for url in matches:
            url = url.strip(' "\'')
            if url and not url.startswith('data:'):
                final_url = urllib.parse.urljoin(base_url, url)
                if len(final_url) > 10:
                    return final_url
    
    return ""

def extract_product_url_advanced(element, base_url):
    """Extraction avancée de l'URL du produit"""
    # Chercher tous les liens
    links = element.find_all('a', href=True)
    for link in links:
        href = link.get('href')
        if href and not href.startswith(('javascript:', '#', 'mailto:')):
            # Vérifier si le lien semble mener à un produit
            link_text = extract_text(link).lower()
            product_indicators = ['détails', 'details', 'voir', 'view', 'product', 'produit', 'acheter', 'buy']
            
            if any(indicator in link_text for indicator in product_indicators) or len(link_text) > 5:
                return urllib.parse.urljoin(base_url, href)
    
    # Prendre le premier lien valide
    if links:
        href = links[0].get('href')
        if href and not href.startswith(('javascript:', '#')):
            return urllib.parse.urljoin(base_url, href)
    
    return ""


def extract_products_from_structured_data(soup, base_url):
    """Extrait les produits depuis les données structurées (JSON-LD)"""
    products = []
    
    # Chercher les scripts JSON-LD
    script_tags = soup.find_all('script', type='application/ld+json')
    for script in script_tags:
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                data = [data]
            
            for item in data if isinstance(data, list) else [data]:
                product_data = extract_from_structured_item(item, base_url)
                if product_data and product_data.get('name'):
                    products.append(product_data)
        except Exception as e:
            continue
    
    return products

def extract_from_structured_item(item, base_url):
    """Extrait les données d'un item structuré"""
    product_data = {}
    
    # Vérifier le type
    item_type = item.get('@type', '')
    if 'Product' not in item_type:
        return None
    
    # Nom
    if item.get('name'):
        product_data['name'] = item['name']
    
    # Prix
    if item.get('offers') and isinstance(item['offers'], dict):
        price = item['offers'].get('price')
        if price:
            product_data['price'] = f"{price} {item['offers'].get('priceCurrency', '€')}"
    
    # Description
    if item.get('description'):
        product_data['description'] = item['description'][:500]
    
    # Image
    if item.get('image'):
        image = item['image']
        if isinstance(image, str):
            product_data['image'] = urllib.parse.urljoin(base_url, image)
        elif isinstance(image, list) and image:
            product_data['image'] = urllib.parse.urljoin(base_url, image[0])
    
    # URL
    if item.get('url'):
        product_data['product_url'] = urllib.parse.urljoin(base_url, item['url'])
    
    return product_data
# ================================
# ROUTES FLASK (inchangées)
# ================================
@app.route("/", methods=["GET"])
def index():
    return render_template("index_promotions.html", playwright_available=PLAYWRIGHT_AVAILABLE)

@app.route("/scrape_promotions", methods=["POST"])
def scrape_promotions():
    start_url = request.form.get("start_url", "").strip()
    render_js = True if request.form.get("render_js") == "on" else False

    if not start_url:
        flash("URL manquante.", "danger")
        return redirect(url_for("index"))

    parsed = urllib.parse.urlparse(start_url)
    if not parsed.scheme:
        start_url = "http://" + start_url

    html = None
    error = None
    if render_js and PLAYWRIGHT_AVAILABLE:
        html, error = fetch_with_playwright(start_url)
        if html is None:
            html, error = fetch_with_requests(start_url)
    else:
        html, error = fetch_with_requests(start_url)
        if html is None and PLAYWRIGHT_AVAILABLE:
            html, error = fetch_with_playwright(start_url)

    # Créer la structure de données compatible avec RAG
    site_id = hashlib.md5(start_url.encode("utf-8")).hexdigest()[:8]
    
    results = {
        "site_id": site_id,
        "start_url": start_url,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "error": error,
        "promoted_products": []
    }

    # Extraction des produits
    if html:
        products = extract_promoted_from_homepage(html, start_url)
        results["promoted_products"] = products
        results["products_count"] = len(products)
    else:
        results["promoted_products"] = []
        results["products_count"] = 0

    # Modifier la structure pour utiliser 'promoted_products' au lieu de 'products'
    new_site_data = {
        "site_id": site_id,
        "start_url": start_url,
        "scraped_count": 1,
        "results": [{
            "url": start_url,
            "title": "Produits extraits",
            "promoted_products": results["promoted_products"],  # ← CHANGER ICI
            "error": error,
            "fetched_at": results["fetched_at"]
        }]
    }

    # ✅ CHARGER les données existantes AU LIEU de les écraser
    path = "last_promotions.json"
    existing_data = {}
    
    # Charger les données existantes si le fichier existe
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            print(f"✅ Données existantes chargées: {len(existing_data)} sites")
        except Exception as e:
            print(f"❌ Erreur lecture fichier existant: {e}")
            existing_data = {}
    
    # ✅ Vérifier si ce site existe déjà
    if site_id in existing_data:
        # Site existant: incrémenter le compteur et ajouter le nouveau résultat
        existing_data[site_id]["scraped_count"] += 1
        existing_data[site_id]["results"].append(new_site_data["results"][0])
        print(f"✅ Site {start_url} mis à jour (scrap #{existing_data[site_id]['scraped_count']})")
    else:
        # Nouveau site: ajouter aux données
        existing_data[site_id] = new_site_data
        print(f"✅ Nouveau site ajouté: {start_url}")

    # ✅ Sauvegarder TOUTES les données (anciennes + nouvelles)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)

    # Réinitialiser le RAG avec toutes les données
    init_rag()

    flash(f"Scraping terminé — {results['products_count']} produits détectés. Total: {len(existing_data)} site(s) sauvegardé(s).", "success")
    return render_template("results_promotions.html", results=results)

@app.route("/rag_chat", methods=["GET"])
def rag_chat():
    if not os.path.exists("last_promotions.json"):
        flash("Aucun produit disponible. Lance d'abord un scraping.", "warning")
        return redirect(url_for("index"))
    return render_template("rag_chat.html")

@app.route("/rag_query", methods=["POST"])
def rag_query():
    global rag
    if not rag:
        init_rag()
    
    question = request.form.get("question", "").strip()
    if not question:
        flash("Veuillez entrer une question.", "warning")
        return redirect(url_for("rag_chat"))

    try:
        response = rag.ask_question(question)
        return render_template("rag_chat.html", question=question, response=response)
    except Exception as e:
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for("rag_chat"))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)