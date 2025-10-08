import json
import os
import requests
from typing import List, Dict, Any
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
import re
import hashlib

class RAGSystem:
    def __init__(self, mistral_api_key: str):
        self.mistral_api_key = mistral_api_key
        self.mistral_api_url = "https://api.mistral.ai/v1/chat/completions"
        
         # Modèle d'embeddings - chargement différé
        self.embedding_model = None
        self.embedding_dim = 384
        self.embedding_model_loaded = False
        
        # Index FAISS
        self.index = None
        self.documents = []
        self.metadata = []
        self.raw_data = None
        
        # Suivi des données
        self.data_hash = None
        self.last_loaded_file = None
        self.is_initialized = False
        
    def _load_embedding_model(self):
        """Charge le modèle d'embeddings seulement si nécessaire"""
        if not self.embedding_model_loaded or self.embedding_model is None:
            print("📦 Chargement du modèle d'embeddings...")
            try:
                self.embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
                self.embedding_model_loaded = True
                print("✅ Modèle d'embeddings chargé avec succès")
            except Exception as e:
                print(f"❌ Erreur lors du chargement du modèle d'embeddings: {e}")
                raise e
        
    def check_data_changes(self, file_path: str = "last_scrape.json") -> Dict:
        """Vérifie si les données ont changé sans les charger"""
        if not os.path.exists(file_path):
            return {'has_changes': True, 'reason': 'file_not_found'}
        
        with open(file_path, 'r', encoding='utf-8') as f:
            file_content = f.read()
            new_hash = self._calculate_data_hash(file_content)
        
        changes_detected = (
            not self.is_initialized or 
            self.data_hash != new_hash or 
            self.last_loaded_file != file_path
        )
        
        return {
            'has_changes': changes_detected,
            'current_hash': self.data_hash,
            'new_hash': new_hash,
            'is_initialized': self.is_initialized,
            'reason': 'not_initialized' if not self.is_initialized else 'data_changed' if self.data_hash != new_hash else 'no_changes'
        }
        
    def load_scraped_data(self, file_path: str = "last_scrape.json"):
        """Charge TOUTES les données du fichier last_scrape.json"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Fichier {file_path} non trouvé")
        
        print("📥 Chargement des données depuis last_scrape.json...")
        
        # Charger le modèle d'embeddings AVANT de traiter les données
        self._load_embedding_model()
        
        with open(file_path, 'r', encoding='utf-8') as f:
            self.raw_data = json.load(f)
        
        self.documents = []
        self.metadata = []
        
        # Gérer le format avec site_id comme clé
        total_products = 0
        total_pages = 0
        total_promoted_products = 0
        
        for site_id, site_data in self.raw_data.items():
            if not isinstance(site_data, dict):
                continue
                
            # 1. Informations générales du site
            start_url = site_data.get('start_url', 'Inconnu')
            scraped_count = site_data.get('scraped_count', 0)
            
            general_info = f"SITE_{site_id}: URL={start_url} | Pages={scraped_count}"
            self.documents.append(general_info)
            self.metadata.append({
                'type': 'site_info',
                'site_id': site_id,
                'category': 'metadata'
            })
            
            # 2. Traiter chaque page avec TOUTES ses données
            results = site_data.get('results', [])
            if not isinstance(results, list):
                continue
                
            for i, page in enumerate(results):
                if not isinstance(page, dict):
                    continue
                    
                total_pages += 1
                
                # A. Métadonnées complètes de la page
                page_documents = self._create_page_documents(page, i, site_id)
                for doc in page_documents:
                    self.documents.append(doc['content'])
                    self.metadata.append(doc['metadata'])
                
                # B. PRODUITS NORMAUX de la page
                normal_products = page.get('products', [])
                for j, product in enumerate(normal_products):
                    if isinstance(product, dict):
                        product_data = self._create_product_document(
                            product, page.get('url', ''), site_id, i, j, "normal"
                        )
                        if product_data:
                            self.documents.append(product_data['content'])
                            self.metadata.append(product_data['metadata'])
                            total_products += 1
                
                # C. PRODUITS PROMUS de la page
                promoted_products = page.get('promoted_products', [])
                for j, product in enumerate(promoted_products):
                    if isinstance(product, dict):
                        product_data = self._create_product_document(
                            product, page.get('url', ''), site_id, i, j, "promoted"
                        )
                        if product_data:
                            self.documents.append(product_data['content'])
                            self.metadata.append(product_data['metadata'])
                            total_promoted_products += 1
                
                # D. Footer de la page
                footer_documents = self._create_footer_documents(page, i, site_id)
                for doc in footer_documents:
                    self.documents.append(doc['content'])
                    self.metadata.append(doc['metadata'])
        
        print(f"✅ {len(self.documents)} documents chargés")
        print(f"📊 Statistiques: {total_products} produits normaux, {total_promoted_products} produits promus, {total_pages} pages")
        
        # Construire l'index FAISS
        if self.documents:
            self._build_faiss_index()
            self.is_initialized = True
        else:
            print("⚠️ Aucun document à indexer")
            self.is_initialized = False
        
    def _calculate_data_hash(self, data_content: str) -> str:
        """Calcule un hash MD5 du contenu des données"""
        return hashlib.md5(data_content.encode('utf-8')).hexdigest()
    
    def is_up_to_date(self, file_path: str = "last_scrape.json") -> bool:
        """Vérifie si le RAG est à jour avec les données"""
        if not os.path.exists(file_path):
            return False
            
        if self.data_hash is None or self.index is None:
            return False
        
        with open(file_path, 'r', encoding='utf-8') as f:
            file_content = f.read()
            current_hash = self._calculate_data_hash(file_content)
        
        return (self.data_hash == current_hash and 
                self.last_loaded_file == file_path)
    
    def _build_faiss_index(self):
        """Construit l'index FAISS à partir des documents"""
        print("🔨 Construction de l'index FAISS...")
        
        # Générer les embeddings pour tous les documents
        print("🧮 Génération des embeddings...")
        embeddings = self.embedding_model.encode(
            self.documents,
            show_progress_bar=True,
            batch_size=32,
            normalize_embeddings=True  # Normalisation pour utiliser cosine similarity
        )
        
        # Créer l'index FAISS
        # IndexFlatIP pour Inner Product (équivalent à cosine similarity avec vecteurs normalisés)
        self.index = faiss.IndexFlatIP(self.embedding_dim)
        
        # Ajouter les embeddings à l'index
        self.index.add(embeddings.astype('float32'))
        
        print(f"✅ Index FAISS créé avec {self.index.ntotal} vecteurs")
        
   
    def _create_page_documents(self, page: Dict, page_index: int, site_id: str) -> List[Dict]:
        """Crée les documents pour une page"""
        documents = []
        page_url = page.get('url', '')
        
        # Document principal de la page
        text_parts = []
        if page.get('title'):
            text_parts.append(f"TITRE_PAGE: {page['title']}")
        if page.get('url'):
            text_parts.append(f"URL: {page['url']}")
        if page.get('meta_description'):
            text_parts.append(f"DESCRIPTION: {page['meta_description']}")
        if page.get('h1'):
            text_parts.append(f"H1: {page['h1']}")
        if page.get('excerpt'):
            excerpt = page['excerpt'][:1000] if len(page['excerpt']) > 1000 else page['excerpt']
            text_parts.append(f"CONTENU: {excerpt}")
        
        text_parts.append(f"PROFONDEUR: {page.get('depth', 0)}")
        text_parts.append(f"NOMBRE_PRODUITS: {len(page.get('products', []))}")
        text_parts.append(f"NOMBRE_IMAGES: {len(page.get('images', []))}")
        
        if text_parts:
            documents.append({
                'content': " | ".join(text_parts),
                'metadata': {
                    'type': 'page',
                    'site_id': site_id,
                    'url': page_url,
                    'title': page.get('title', ''),
                    'page_index': page_index,
                    'category': 'page_metadata'
                }
            })
        
        return documents
    
    def _create_products_documents(self, page: Dict, page_index: int, site_id: str) -> List[Dict]:
        """Crée les documents pour TOUS les produits d'une page (normaux + promus)"""
        documents = []
        page_url = page.get('url', '')
        
        # Produits normaux
        normal_products = page.get('products', [])
        if not isinstance(normal_products, list):
            normal_products = []
        
        # Produits promus
        promoted_products = page.get('promoted_products', [])
        if not isinstance(promoted_products, list):
            promoted_products = []
        
        print(f"📦 Page {page_url}: {len(normal_products)} produits normaux, {len(promoted_products)} produits promus")
        
        # Traiter les produits normaux
        for j, product in enumerate(normal_products):
            if not isinstance(product, dict):
                continue
                
            product_data = self._create_product_document(product, page_url, site_id, page_index, j, "normal")
            if product_data:
                documents.append(product_data)
        
        # Traiter les produits promus
        for j, product in enumerate(promoted_products):
            if not isinstance(product, dict):
                continue
                
            product_data = self._create_product_document(product, page_url, site_id, page_index, j, "promoted")
            if product_data:
                documents.append(product_data)
        
        return documents

    def _create_product_document(self, product: Dict, page_url: str, site_id: str, page_index: int, product_index: int, product_type: str) -> Dict:
        """Crée un document pour un produit (normal ou promu)"""
        text_parts = []
        
        # Informations produit de base
        if product.get('name'):
            text_parts.append(f"PRODUIT_NOM: {product['name']}")
        
        if product.get('price'):
            price_text = product['price'].replace('€', ' euro ').replace('$', ' dollar ')
            text_parts.append(f"PRIX: {price_text}")
            text_parts.append(f"PRIX_NUMERIQUE: {price_text}")
        
        if product.get('description'):
            desc = product['description'][:500] if len(product['description']) > 500 else product['description']
            text_parts.append(f"DESCRIPTION: {desc}")
        
        if product.get('sku'):
            text_parts.append(f"REFERENCE: {product['sku']}")
        
        if product.get('image'):
            text_parts.append("IMAGE_DISPONIBLE: oui")
        
        if product.get('product_url'):
            text_parts.append(f"URL_PRODUIT: {product['product_url']}")
        
        # Type de produit
        text_parts.append(f"TYPE_PRODUIT: {product_type}")
        if product_type == "promoted":
            text_parts.append("PROMU: oui")
            text_parts.append("PRODUIT_EN_AVANT: oui")
            promotion_indicators = product.get('promotion_indicators', [])
            if promotion_indicators:
                text_parts.append(f"INDICATEURS_PROMOTION: {', '.join(promotion_indicators)}")
        else:
            text_parts.append("PROMU: non")
        
        # Mots-clés pour améliorer la recherche
        text_parts.append("CATEGORIE: produit")
        text_parts.append("E_COMMERCE: oui")
        
        if text_parts:
            return {
                'content': " | ".join(text_parts),
                'metadata': {
                    'type': 'product',
                    'product_type': product_type,
                    'site_id': site_id,
                    'page_url': page_url,
                    'product_name': product.get('name', ''),
                    'price': product.get('price', ''),
                    'page_index': page_index,
                    'product_index': product_index,
                    'category': 'product',
                    'is_promoted': (product_type == "promoted")
                }
            }
        
        return None
    
    def _create_footer_documents(self, page: Dict, page_index: int, site_id: str) -> List[Dict]:
        """Crée les documents pour le footer"""
        documents = []
        footer = page.get('footer', {})
        if not footer or not isinstance(footer, dict):
            return documents
        
        page_url = page.get('url', '')
        
        # Footer textuel
        if footer.get('text'):
            footer_text = footer['text'][:800] if len(footer['text']) > 800 else footer['text']
            documents.append({
                'content': f"FOOTER: {footer_text}",
                'metadata': {
                    'type': 'footer',
                    'site_id': site_id,
                    'url': page_url,
                    'page_index': page_index,
                    'category': 'footer'
                }
            })
        
        # Liens du footer
        links = footer.get('links', [])
        if links and isinstance(links, list):
            links_text = " | ".join([f"{link.get('text', '')} -> {link.get('url', '')}" 
                                    for link in links[:5] if isinstance(link, dict)])
            if links_text:
                documents.append({
                    'content': f"LIENS_FOOTER: {links_text}",
                    'metadata': {
                        'type': 'footer_links',
                        'site_id': site_id,
                        'url': page_url,
                        'links_count': len(links),
                        'page_index': page_index,
                        'category': 'footer'
                    }
                })
        
        return documents
    
    def search(self, query: str, k: int = 20) -> List[Dict]:
        """Recherche améliorée avec FAISS"""
        if self.index is None or not self.documents:
            return []
        
        try:
            # Générer l'embedding de la requête
            query_embedding = self.embedding_model.encode(
                [query],
                normalize_embeddings=True
            ).astype('float32')
            
            # Rechercher dans l'index FAISS
            scores, indices = self.index.search(query_embedding, k)
            
            # Construire les résultats
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < len(self.documents) and score > 0.3:  # Seuil de similarité
                    results.append({
                        'document': self.documents[idx],
                        'metadata': self.metadata[idx],
                        'score': float(score)
                    })
            
            # Trier par pertinence avec boosting
            results = self._sort_by_relevance(results, query)
            
            return results
            
        except Exception as e:
            print(f"❌ Erreur recherche: {e}")
            return []

    def _sort_by_relevance(self, results, query):
        """Trie les résultats par pertinence pour la requête"""
        query_lower = query.lower()
        
        def relevance_score(item):
            score = item['score']
            metadata = item['metadata']
            document = item['document'].lower()
            
            # Booster les produits
            if metadata.get('category') == 'product' or metadata.get('type') == 'product':
                score *= 1.5
            
            # Booster si la requête contient des mots spécifiques
            if 'promo' in query_lower and metadata.get('is_promoted'):
                score *= 2.0
            if 'prix' in query_lower and 'PRIX:' in document:
                score *= 1.5
            if 'description' in query_lower and 'DESCRIPTION:' in document:
                score *= 1.3
                
            return score
        
        return sorted(results, key=relevance_score, reverse=True)
    
    def generate_response(self, query: str, context: List[Dict] = None) -> str:
        """Génère une réponse basée sur TOUTES les données disponibles"""
        if context is None:
            context = self.search(query)
        
        context_text = self._format_context(context)
        
        system_prompt = """TU ES UN EXPERT EN MARKETING DIGITAL.

TU ES UN EXPERT SENIOR EN DIGITAL MARKETING & E-COMMERCE avec 15 ans d'expérience.

# DOMAINES D'EXPERTISE
- Analyse de sites e-commerce
- Optimisation du taux de conversion (CRO)
- Stratégies de contenu et SEO
- Analyse des produits et pricing
- Marketing des promotions
- Expérience utilisateur (UX)
- Analytics et performance

# CONTEXTE DES DONNÉES
Tu as accès à des données scrapées de sites e-commerce contenant :
• PRODUITS NORMALS → Catalogue standard
• PRODUITS PROMUS → Mise en avant spéciale (promotions, vedettes)
• MÉTADONNÉES → Titres, descriptions, prix, images
• STRUCTURE SITE → Pages, navigation, contenu

Réponds toujours en français, sois exhaustif et précis."""

        user_prompt = f"""QUESTION: {query}

CONTEXTE COMPLET (toutes les données scrapées de tous les sites):
{context_text}

En tant qu'expert en marketing digital, analyse toutes les données ci-dessus et fournis une réponse COMPLÈTE, STRUCTURÉE et PRÉCISE. 
Organise les produits par site, différencie clairement produits normaux et promus, donne tous les détails importants.

RÉPONSE DÉTAILLÉE:"""
        
        headers = {
            "Authorization": f"Bearer {self.mistral_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "mistral-medium",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 2000
        }
        
        try:
            print("🔄 Génération de la réponse avec Mistral...")
            response = requests.post(self.mistral_api_url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
        except Exception as e:
            return f"❌ Erreur API Mistral: {str(e)}"
    
    def _format_context(self, context: List[Dict]) -> str:
        """Formate le contexte pour le prompt"""
        if not context:
            return "AUCUNE DONNÉE PERTINENTE TROUVÉE DANS LES SITES SCRAPÉS"
        
        # Grouper par site pour meilleure organisation
        sites_data = {}
        
        for item in context:
            site_id = item['metadata'].get('site_id', 'unknown')
            if site_id not in sites_data:
                sites_data[site_id] = {
                    'products': [],
                    'pages': [],
                    'footers': [],
                    'site_info': []
                }
            
            category = item['metadata'].get('category')
            doc_type = item['metadata'].get('type')
            
            if category == 'product' or doc_type == 'product':
                sites_data[site_id]['products'].append(item)
            elif category == 'page_metadata' or doc_type == 'page':
                sites_data[site_id]['pages'].append(item)
            elif category == 'footer' or doc_type in ['footer', 'footer_links']:
                sites_data[site_id]['footers'].append(item)
            elif doc_type == 'site_info':
                sites_data[site_id]['site_info'].append(item)
        
        context_parts = ["=== DONNÉES COMPLÈTES (TOUS LES SITES) ==="]
        
        # Afficher les données par site
        for site_id, site_data in sites_data.items():
            context_parts.append(f"\n🏠 SITE: {site_id}")
            
            # Informations du site
            if site_data['site_info']:
                for info in site_data['site_info']:
                    context_parts.append(f"📋 Info Site: {info['document']}")
            
            # Produits (priorité)
            if site_data['products']:
                context_parts.append(f"\n🎯 PRODUITS TROUVÉS ({len(site_data['products'])}):")
                for i, item in enumerate(site_data['products'], 1):
                    context_parts.append(f"\n--- Produit {i} (pertinence: {item['score']:.3f}) ---")
                    context_parts.append(f"{item['document']}")
            
            # Pages
            if site_data['pages']:
                context_parts.append(f"\n📄 PAGES ({len(site_data['pages'])}):")
                for i, item in enumerate(site_data['pages'], 1):
                    context_parts.append(f"\n--- Page {i} (pertinence: {item['score']:.3f}) ---")
                    context_parts.append(f"{item['document']}")
            
            # Footers
            if site_data['footers']:
                context_parts.append(f"\n🦶 FOOTERS ({len(site_data['footers'])}):")
                for i, item in enumerate(site_data['footers'], 1):
                    context_parts.append(f"\n--- Footer {i} (pertinence: {item['score']:.3f}) ---")
                    context_parts.append(f"{item['document']}")
        
        context_parts.append("\n=== FIN DES DONNÉES ===")
        return "\n".join(context_parts)
    
    def ask_question(self, question: str) -> str:
        """Pose une question sur TOUTES les données"""
        if not self.documents:
            return "❌ Aucune donnée chargée. Effectuez d'abord un scraping et initialisez le système RAG."
        
        print(f"🔍 Recherche dans les données: '{question}'")
        relevant_docs = self.search(question, k=15)
        
        if not relevant_docs:
            return "❌ Aucune information pertinente trouvée dans les données scrapées."
        
        # Statistiques détaillées par site
        sites_stats = {}
        for doc in relevant_docs:
            site_id = doc['metadata'].get('site_id', 'unknown')
            if site_id not in sites_stats:
                sites_stats[site_id] = {
                    'products': 0, 
                    'pages': 0, 
                    'footers': 0,
                    'site_info': 0
                }
            
            category = doc['metadata'].get('category')
            doc_type = doc['metadata'].get('type')
            
            if category == 'product' or doc_type == 'product':
                sites_stats[site_id]['products'] += 1
            elif category == 'page_metadata' or doc_type == 'page':
                sites_stats[site_id]['pages'] += 1
            elif category == 'footer' or doc_type in ['footer', 'footer_links']:
                sites_stats[site_id]['footers'] += 1
            elif doc_type == 'site_info':
                sites_stats[site_id]['site_info'] += 1
        
        print(f"📊 {len(relevant_docs)} documents pertinents trouvés sur {len(sites_stats)} sites")
        for site_id, stats in sites_stats.items():
            print(f"   - Site {site_id}: {stats['products']} produits, {stats['pages']} pages, {stats['footers']} footers")
        
        print("🤖 Génération de la réponse...")
        response = self.generate_response(question, relevant_docs)
        return response

    def get_stats(self) -> Dict:
        """Retourne les statistiques complètes"""
        if not self.raw_data:
            return {'initialized': False}
        
        total_sites = len(self.raw_data)
        total_pages = 0
        total_products = 0
        total_promoted_products = 0
        
        # Compter par site avec plus de détails
        sites_details = {}
        for site_id, site_data in self.raw_data.items():
            if isinstance(site_data, dict):
                results = site_data.get('results', [])
                site_pages = len(results) if isinstance(results, list) else 0
                site_products = 0
                site_promoted_products = 0
                
                if isinstance(results, list):
                    for page in results:
                        if isinstance(page, dict):
                            products = page.get('products', [])
                            if isinstance(products, list):
                                site_products += len(products)
                            promoted_products = page.get('promoted_products', [])
                            if isinstance(promoted_products, list):
                                site_promoted_products += len(promoted_products)
                
                total_pages += site_pages
                total_products += site_products
                total_promoted_products += site_promoted_products
                
                sites_details[site_id] = {
                    'pages': site_pages,
                    'products': site_products,
                    'promoted_products': site_promoted_products,
                    'start_url': site_data.get('start_url', 'N/A')
                }
        
        # Compter par catégorie dans les documents
        product_docs = len([m for m in self.metadata if m.get('category') == 'product' or m.get('type') == 'product'])
        page_docs = len([m for m in self.metadata if m.get('category') == 'page_metadata' or m.get('type') == 'page'])
        footer_docs = len([m for m in self.metadata if m.get('category') == 'footer' or m.get('type') in ['footer', 'footer_links']])
        
        stats = {
            'initialized': self.index is not None,
            'total_sites': total_sites,
            'total_pages': total_pages,
            'total_products': total_products,
            'total_documents': len(self.documents),
            'product_documents': product_docs,
            'page_documents': page_docs,
            'footer_documents': footer_docs,
            'sites': list(self.raw_data.keys()) if self.raw_data else [],
            'index_size': self.index.ntotal if self.index else 0
        }
        return stats

    def list_sites(self) -> List[Dict]:
        """Liste tous les sites disponibles avec leurs statistiques"""
        if not self.raw_data:
            return []
        
        sites_list = []
        for site_id, site_data in self.raw_data.items():
            if isinstance(site_data, dict):
                sites_list.append({
                    'site_id': site_id,
                    'start_url': site_data.get('start_url', 'N/A'),
                    'scraped_count': site_data.get('scraped_count', 0),
                    'max_pages': site_data.get('max_pages', 0),
                    'max_depth': site_data.get('max_depth', 0)
                })
        
        return sites_list

# Singleton pour le système RAG
_rag_instance = None

def get_rag_system(api_key: str = None):
    """
    Récupère ou initialise une instance du système RAG.
    """
    global _rag_instance
    if _rag_instance is None:
        if api_key is None:
            api_key = os.getenv("MISTRAL_API_KEY")

        if not api_key:
            print("⚠️ Aucune clé MISTRAL_API_KEY détectée — le RAG fonctionnera en mode local sans LLM.")
            api_key = "LOCAL_MODE"

        try:
            _rag_instance = RAGSystem(api_key)
        except Exception as e:
            print(f"❌ Erreur lors de la création du RAGSystem : {e}")
            _rag_instance = None

    return _rag_instance

def initialize_rag(self, file_path: str = "last_scrape.json") -> bool:
        """Initialise manuellement le RAG seulement si demandé"""
        print("🚀 Initialisation manuelle du RAG demandée...")
        
        # Charger le modèle d'embeddings
        self.load_embedding_model()
        
        # Vérifier les changements
        changes = self.check_data_changes(file_path)
        
        if not changes['has_changes'] and self.is_initialized:
            print("✅ RAG déjà à jour - Pas besoin de réinitialisation")
            return True
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Fichier {file_path} non trouvé")
        
        # Charger les données
        with open(file_path, 'r', encoding='utf-8') as f:
            file_content = f.read()
            self.raw_data = json.loads(file_content)
            self.data_hash = self._calculate_data_hash(file_content)
            self.last_loaded_file = file_path
        
        self.documents = []
        self.metadata = []
        
        print("📥 Chargement des données depuis last_scrape.json...")
        
        # [Le reste du code de chargement des données reste identique]
        total_products = 0
        total_pages = 0
        total_promoted_products = 0
        
        for site_id, site_data in self.raw_data.items():
            if not isinstance(site_data, dict):
                continue
                
            # 1. Informations générales du site
            start_url = site_data.get('start_url', 'Inconnu')
            scraped_count = site_data.get('scraped_count', 0)
            
            general_info = f"SITE_{site_id}: URL={start_url} | Pages={scraped_count}"
            self.documents.append(general_info)
            self.metadata.append({
                'type': 'site_info',
                'site_id': site_id,
                'category': 'metadata'
            })
            
            # 2. Traiter chaque page
            results = site_data.get('results', [])
            if not isinstance(results, list):
                continue
                
            for i, page in enumerate(results):
                if not isinstance(page, dict):
                    continue
                    
                total_pages += 1
                
                # A. Métadonnées de la page
                page_documents = self._create_page_documents(page, i, site_id)
                for doc in page_documents:
                    self.documents.append(doc['content'])
                    self.metadata.append(doc['metadata'])
                
                # B. PRODUITS NORMAUX
                normal_products = page.get('products', [])
                for j, product in enumerate(normal_products):
                    if isinstance(product, dict):
                        product_data = self._create_product_document(
                            product, page.get('url', ''), site_id, i, j, "normal"
                        )
                        if product_data:
                            self.documents.append(product_data['content'])
                            self.metadata.append(product_data['metadata'])
                            total_products += 1
                
                # C. PRODUITS PROMUS
                promoted_products = page.get('promoted_products', [])
                for j, product in enumerate(promoted_products):
                    if isinstance(product, dict):
                        product_data = self._create_product_document(
                            product, page.get('url', ''), site_id, i, j, "promoted"
                        )
                        if product_data:
                            self.documents.append(product_data['content'])
                            self.metadata.append(product_data['metadata'])
                            total_promoted_products += 1
                
                # D. Footer
                footer_documents = self._create_footer_documents(page, i, site_id)
                for doc in footer_documents:
                    self.documents.append(doc['content'])
                    self.metadata.append(doc['metadata'])
        
        print(f"✅ {len(self.documents)} documents chargés")
        print(f"📊 Statistiques: {total_products} produits normaux, {total_promoted_products} produits promus, {total_pages} pages")
        
        # Construire l'index FAISS
        if self.documents:
            self._build_faiss_index()
            self.is_initialized = True
            print("🎉 RAG initialisé avec succès!")
            return True
        else:
            print("⚠️ Aucun document à indexer")
            return False
    
def can_answer_questions(self) -> bool:
    """Vérifie si le système peut répondre aux questions"""
    return self.is_initialized and self.index is not None and len(self.documents) > 0


def initialize_rag_system(api_key: str = None, force_reload: bool = False):
    """Initialise le système RAG seulement si nécessaire"""
    rag_system = get_rag_system(api_key)
    
    try:
        # Vérifier si le RAG est déjà à jour
        if not force_reload and rag_system.is_up_to_date():
            stats = rag_system.get_stats()
            message = (f"✅ RAG déjà à jour - {stats['total_sites']} sites, "
                      f"{stats['total_pages']} pages, {stats['total_products']} produits, "
                      f"{stats['total_documents']} documents")
            return True, message
        
        # Charger les données (seulement si nécessaire)
        data_loaded = rag_system.load_scraped_data()
        
        stats = rag_system.get_stats()
        if stats['initialized']:
            if data_loaded:
                message = (f"✅ RAG initialisé - {stats['total_sites']} sites, "
                          f"{stats['total_pages']} pages, {stats['total_products']} produits, "
                          f"{stats['total_documents']} documents, "
                          f"Index FAISS: {stats['index_size']} vecteurs")
            else:
                message = (f"✅ RAG déjà initialisé - {stats['total_sites']} sites, "
                          f"{stats['total_pages']} pages, {stats['total_products']} produits")
            return True, message
        else:
            return False, "❌ Échec initialisation du RAG"
            
    except FileNotFoundError:
        return False, "❌ Fichier last_scrape.json non trouvé. Effectuez d'abord un scraping."
    except Exception as e:
        return False, f"❌ Erreur lors de l'initialisation: {str(e)}"