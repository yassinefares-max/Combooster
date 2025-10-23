# extra_routes.py
from flask import Blueprint, request, jsonify, send_file
import csv
import io
import os
import json
from RagSystem.rag_system import get_rag_system

extra_routes = Blueprint("extra_routes", __name__)

# Chemin du fichier JSON généré par le scraping
DATA_FILE = "last_scrape.json"


# ===============================
# 1. Télécharger les produits promus
# ===============================
@extra_routes.route("/download_promoted_csv")
def download_promoted_csv():
    """
    Télécharge un CSV des produits marqués 'promoted' dans last_scrape.json.
    Fonction robuste : supporte la structure avec site_id comme clé.
    """
    if not os.path.exists(DATA_FILE):
        return jsonify({"error": "Aucun fichier de scraping trouvé"}), 404

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data_all = json.load(f)
    except json.JSONDecodeError:
        return jsonify({"error": "Fichier JSON invalide (last_scrape.json)"}), 500
    except Exception as e:
        return jsonify({"error": f"Impossible de lire le fichier: {str(e)}"}), 500

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["site_id", "site_url", "Nom", "Prix", "Raisons", "URL_de_la_page", "URL_du_produit"])

    # Gérer le format avec site_id comme clé (format actuel de votre app)
    products_found = 0
    
    for site_id, site_data in data_all.items():
        if not isinstance(site_data, dict):
            continue
            
        site_url = site_data.get("start_url", "")
        results = site_data.get("results", [])
        
        if not isinstance(results, list):
            continue
        
        for page in results:
            if not isinstance(page, dict):
                continue
                
            page_url = page.get("url", "")
            products = page.get("products", [])
            
            if not isinstance(products, list):
                continue
            
            for p in products:
                if not isinstance(p, dict):
                    continue
                    
                promoted_flag = p.get("promoted", False)
                
                if promoted_flag:
                    name = p.get("name", "")
                    price = p.get("price", "")
                    reasons = p.get("promoted_reasons", [])
                    
                    if isinstance(reasons, list):
                        reasons_text = ", ".join(str(r) for r in reasons)
                    else:
                        reasons_text = str(reasons) if reasons else ""
                    
                    product_page_url = p.get("product_url", "")
                    
                    writer.writerow([site_id, site_url, name, price, reasons_text, page_url, product_page_url])
                    products_found += 1

    output.seek(0)
    
    # Si aucun produit promu trouvé, retourner un message
    if products_found == 0:
        return jsonify({
            "error": "Aucun produit promu trouvé dans les données",
            "tip": "Les produits doivent avoir un champ 'promoted': true pour apparaître ici"
        }), 404
    
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="produits_promus.csv"
    )


# ===============================
# 2. Génération de campagnes marketing
# ===============================
@extra_routes.route("/generate_campaign", methods=["POST"])
def generate_campaign():
    """Génère des campagnes marketing pour un produit"""
    try:
        # Vérifier que l'API key Mistral est configurée
        mistral_api_key = os.getenv("MISTRAL_API_KEY")
        if not mistral_api_key:
            return jsonify({"error": "Clé API Mistral non configurée"}), 500
        
        rag = get_rag_system(mistral_api_key)
        
        # Vérifier que le RAG est initialisé
        stats = rag.get_stats()
        if not stats.get('initialized', False):
            return jsonify({
                "error": "Système RAG non initialisé",
                "tip": "Veuillez d'abord initialiser le RAG depuis la page /ask"
            }), 400
        
        data = request.json
        if not data:
            return jsonify({"error": "Données JSON manquantes"}), 400

        product_name = data.get("product_name", "").strip()
        platform = data.get("platform", "instagram")
        tone = data.get("tone", "convivial")
        n_variants = int(data.get("n_variants", 3))

        if not product_name:
            return jsonify({"error": "Nom du produit requis"}), 400
        
        if n_variants < 1 or n_variants > 5:
            n_variants = 3

        # Rechercher le produit dans le RAG
        context = rag.search(product_name, k=5)
        
        if not context:
            return jsonify({
                "error": f"Produit '{product_name}' non trouvé dans les données",
                "tip": "Vérifiez que le produit existe dans les données scrapées"
            }), 404
        
        # Construire le contexte produit
        context_text = "\n".join([c['document'] for c in context[:3]])

        prompt = f"""Génère {n_variants} posts marketing créatifs pour le produit "{product_name}".

Plateforme cible: {platform}
Ton souhaité: {tone}

Contexte du produit:
{context_text}

Instructions:
- Crée {n_variants} variantes différentes et engageantes
- Adapte le contenu à {platform}
- Utilise un ton {tone}
- Inclus des émojis si approprié pour {platform}
- Garde chaque post court et percutant (max 150 caractères)
- Numérote chaque variante

Format de réponse:
1. [Premier post]
2. [Deuxième post]
3. [Troisième post]
"""

        # Utiliser la méthode generate_response existante
        response = rag.generate_response(prompt, context)
        
        # Séparer les variantes (lignes non vides)
        campaigns = []
        for line in response.split('\n'):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith('-') or line.startswith('•')):
                # Nettoyer la numérotation
                cleaned = line.lstrip('0123456789.-•) ').strip()
                if cleaned:
                    campaigns.append(cleaned)
        
        # Si pas de variantes détectées, retourner la réponse brute divisée
        if not campaigns:
            campaigns = [line.strip() for line in response.split('\n') if line.strip()][:n_variants]

        return jsonify({
            "campaigns": campaigns[:n_variants],
            "product": product_name,
            "platform": platform,
            "tone": tone
        })
    
    except ValueError as e:
        return jsonify({"error": f"Erreur de validation: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": f"Erreur serveur: {str(e)}"}), 500