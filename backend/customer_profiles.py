import json
import os
from datetime import datetime
from typing import Dict, List, Any
from pymongo import MongoClient
import hashlib
import re

class CustomerProfileManager:
    """Gestionnaire des profils clients basés sur les sites scrapés"""
    
    def __init__(self, mongo_client=None):
        self.mongo_client = mongo_client or MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"))
        self.db = self.mongo_client["scraping_db"]
        self.collection = self.db["customer_profiles"]
        self.scrapes_collection = self.db["scraped_sites"]
        
        # Créer les index pour une recherche optimisée
        self.collection.create_index("site_id", unique=True)
        self.collection.create_index("domain")
        self.collection.create_index("industry")
    
    def generate_profile_from_scraped_data(self, site_id: str) -> Dict[str, Any]:
        """Génère un profil client automatiquement à partir des données scrapées"""
        
        # Récupérer les données scrapées du site
        scraped_data = self.scrapes_collection.find_one({"site_id": site_id})
        if not scraped_data:
            raise ValueError(f"Aucune donnée scrapée trouvée pour le site {site_id}")
        
        # Analyser les données pour créer le profil
        profile_data = self._analyze_scraped_data(scraped_data)
        
        # Sauvegarder le profil
        profile_data["site_id"] = site_id
        profile_data["created_at"] = datetime.now().isoformat()
        profile_data["updated_at"] = datetime.now().isoformat()
        profile_data["profile_completeness"] = self._calculate_completeness(profile_data)
        
        # Upsert du profil
        self.collection.update_one(
            {"site_id": site_id},
            {"$set": profile_data},
            upsert=True
        )
        
        return profile_data
    
    def _analyze_scraped_data(self, scraped_data: Dict) -> Dict[str, Any]:
        """Analyse les données scrapées pour extraire les informations du profil"""
        
        start_url = scraped_data.get("start_url", "")
        domain = self._extract_domain(start_url)
        results = scraped_data.get("results", [])
        
        # Analyser toutes les pages pour déterminer le type de site
        all_products = []
        all_titles = []
        all_descriptions = []
        homepage_data = None
        
        for page in results:
            if isinstance(page, dict):
                # Collecter les produits
                all_products.extend(page.get("products", []))
                all_products.extend(page.get("promoted_products", []))
                
                # Collecter les métadonnées
                if page.get("title"):
                    all_titles.append(page["title"])
                if page.get("meta_description"):
                    all_descriptions.append(page["meta_description"])
                
                # Identifier la page d'accueil
                if self._is_homepage(page.get("url", ""), page.get("depth", 0)):
                    homepage_data = page
        
        # Déterminer l'industrie et le type de business
        industry, business_type = self._detect_industry_and_business(
            all_titles, all_descriptions, all_products, homepage_data
        )
        
        # Analyser les produits pour déterminer l'audience
        target_audience = self._analyze_target_audience(all_products, all_titles)
        
        # Déterminer la voix de la marque
        brand_voice = self._detect_brand_voice(all_titles, all_descriptions)
        
        # Extraire les valeurs de la marque depuis le footer
        brand_values = self._extract_brand_values(homepage_data)
        
        # Générer le profil
        profile = {
            "company_name": self._extract_company_name(domain, all_titles, homepage_data),
            "domain": domain,
            "website": start_url,
            "industry": industry,
            "business_type": business_type,
            "target_audience": target_audience,
            "brand_voice": brand_voice,
            "brand_values": brand_values,
            "content_preferences": self._analyze_content_preferences(all_products, all_titles),
            "social_media_platforms": self._detect_social_media(homepage_data),
            "business_goals": self._infer_business_goals(industry, business_type, all_products),
            "market_position": self._infer_market_position(all_products, homepage_data),
            "tags": self._generate_tags(industry, business_type, all_products),
            "scraped_stats": {
                "total_pages": len(results),
                "total_products": len(all_products),
                "scraped_at": scraped_data.get("scraped_at", "")
            }
        }
        
        return profile
    
    def _extract_domain(self, url: str) -> str:
        """Extrait le domaine depuis l'URL"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")
    
    def _is_homepage(self, url: str, depth: int) -> bool:
        """Détermine si l'URL est une page d'accueil"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        return depth == 0 or path in ["", "/"] or '/home' in path.lower() or '/accueil' in path.lower()
    
    def _detect_industry_and_business(self, titles: List[str], descriptions: List[str], 
                                    products: List[Dict], homepage_data: Dict) -> tuple:
        """Détecte l'industrie et le type de business"""
        
        # Analyser les textes pour trouver des indices
        all_text = " ".join(titles + descriptions).lower()
        
        # Détection de l'industrie
        industry_keywords = {
            "e-commerce": ["boutique", "shop", "store", "achat", "acheter", "produit", "prix", "panier"],
            "mode": ["vêtement", "fashion", "mode", "habillement", "style", "collection"],
            "technologie": ["tech", "technologie", "digital", "innovation", "solution", "logiciel"],
            "alimentation": ["restaurant", "food", "cuisine", "recette", "menu", "repas"],
            "voyage": ["voyage", "hotel", "vacances", "destination", "tourisme", "vol"],
            "santé": ["santé", "medical", "bien-être", "sport", "fitness", "nutrition"],
            "luxe": ["luxe", "premium", "exclusif", "design", "art", "création"]
        }
        
        industry_scores = {industry: 0 for industry in industry_keywords.keys()}
        
        for industry, keywords in industry_keywords.items():
            for keyword in keywords:
                if keyword in all_text:
                    industry_scores[industry] += 1
        
        # Trouver l'industrie avec le score le plus élevé
        detected_industry = max(industry_scores.items(), key=lambda x: x[1])[0] if industry_scores else "e-commerce"
        
        # Détection du type de business
        business_type = "B2C"  # Par défaut
        if any(word in all_text for word in ["b2b", "entreprise", "professionnel", "business", "corporate"]):
            business_type = "B2B"
        elif len(products) > 0 and any("abonnement" in str(p.get("price", "")).lower() for p in products):
            business_type = "SaaS"
        
        return detected_industry, business_type
    
    def _analyze_target_audience(self, products: List[Dict], titles: List[str]) -> Dict:
        """Analyse l'audience cible basée sur les produits et le contenu"""
        
        all_text = " ".join(titles).lower()
        
        # Détection basique de l'audience
        demographics = []
        
        # Basé sur les prix des produits
        if products:
            prices = []
            for product in products:
                price_text = str(product.get("price", ""))
                price_match = re.search(r'(\d+[.,]\d+)', price_text)
                if price_match:
                    try:
                        price = float(price_match.group(1).replace(',', '.'))
                        prices.append(price)
                    except:
                        pass
            
            if prices:
                avg_price = sum(prices) / len(prices)
                if avg_price < 50:
                    demographics.append("Budget")
                elif avg_price < 200:
                    demographics.append("Moyenne gamme")
                else:
                    demographics.append("Haut de gamme")
        
        # Basé sur le contenu
        if any(word in all_text for word in ["enfant", "bébé", "kids", "child"]):
            demographics.append("Familles")
        elif any(word in all_text for word in ["entreprise", "business", "professionnel"]):
            demographics.append("Professionnels")
        elif any(word in all_text for word in ["jeune", "student", "étudiant"]):
            demographics.append("Jeunes adultes")
        else:
            demographics.append("Grand public")
        
        return {
            "demographics": demographics,
            "price_range": self._detect_price_range(products)
        }
    
    def _detect_price_range(self, products: List[Dict]) -> str:
        """Détecte la gamme de prix"""
        if not products:
            return "Inconnu"
        
        prices = []
        for product in products:
            price_text = str(product.get("price", ""))
            price_match = re.search(r'(\d+[.,]\d+)', price_text)
            if price_match:
                try:
                    price = float(price_match.group(1).replace(',', '.'))
                    prices.append(price)
                except:
                    pass
        
        if not prices:
            return "Inconnu"
        
        avg_price = sum(prices) / len(prices)
        if avg_price < 20:
            return "Entrée de gamme"
        elif avg_price < 100:
            return "Moyenne gamme"
        else:
            return "Haut de gamme"
    
    def _detect_brand_voice(self, titles: List[str], descriptions: List[str]) -> str:
        """Détecte la voix de la marque"""
        all_text = " ".join(titles + descriptions).lower()
        
        if any(word in all_text for word in ["luxe", "premium", "exclusif", "élégant"]):
            return "Sophistiqué"
        elif any(word in all_text for word in ["fun", "amusant", "jeune", "créatif"]):
            return "Décontracté"
        elif any(word in all_text for word in ["expert", "professionnel", "solution", "technique"]):
            return "Professionnel"
        elif any(word in all_text for word in ["innovation", "futur", "technologie", "digital"]):
            return "Innovant"
        else:
            return "Professionnel"  # Par défaut
    
    def _extract_brand_values(self, homepage_data: Dict) -> List[str]:
        """Extrait les valeurs de la marque depuis le footer et la page d'accueil"""
        if not homepage_data:
            return ["Qualité", "Service client"]
        
        footer = homepage_data.get("footer", {})
        footer_text = footer.get("text", "").lower()
        
        values = []
        value_keywords = {
            "qualité": ["qualité", "excellence", "premium"],
            "innovation": ["innovation", "créativité", "avant-garde"],
            "durabilité": ["durable", "écologique", "responsable", "éthique"],
            "service": ["service", "client", "satisfaction", "support"],
            "accessibilité": ["accessible", "abordable", "prix", "value"]
        }
        
        for value, keywords in value_keywords.items():
            if any(keyword in footer_text for keyword in keywords):
                values.append(value.capitalize())
        
        return values if values else ["Qualité", "Service client"]
    
    def _extract_company_name(self, domain: str, titles: List[str], homepage_data: Dict) -> str:
        """Extrait le nom de l'entreprise"""
        if titles:
            # Prendre le titre de la page d'accueil
            for title in titles:
                if title and len(title) > 3:
                    # Nettoyer le titre (enlever les marqueurs de page)
                    clean_title = re.sub(r' - .*$', '', title)
                    clean_title = re.sub(r' \| .*$', '', clean_title)
                    clean_title = re.sub(r' – .*$', '', clean_title)
                    return clean_title[:50]  # Limiter la longueur
        
        # Fallback: utiliser le domaine
        return domain.split('.')[0].capitalize()
    
    def _analyze_content_preferences(self, products: List[Dict], titles: List[str]) -> Dict:
        """Analyse les préférences de contenu"""
        all_text = " ".join(titles).lower()
        
        formats = []
        if any(word in all_text for word in ["blog", "article", "actualité"]):
            formats.append("Articles de blog")
        if len(products) > 0:
            formats.append("Fiches produit")
        if any(word in all_text for word in ["galerie", "portfolio", "image"]):
            formats.append("Galleries photos")
        
        return {
            "formats": formats if formats else ["Fiches produit", "Articles de blog"],
            "topics": self._extract_content_topics(titles, products)
        }
    
    def _extract_content_topics(self, titles: List[str], products: List[Dict]) -> List[str]:
        """Extrait les thèmes de contenu"""
        all_text = " ".join(titles).lower()
        
        topics = []
        if any(word in all_text for word in ["nouveau", "nouvelle", "new", "collection"]):
            topics.append("Nouveautés")
        if any(word in all_text for word in ["promo", "solde", "réduction", "offre"]):
            topics.append("Promotions")
        if len(products) > 0:
            topics.append("Produits")
        
        return topics if topics else ["Produits", "Actualités"]
    
    def _detect_social_media(self, homepage_data: Dict) -> List[str]:
        """Détecte les réseaux sociaux depuis le footer"""
        if not homepage_data:
            return ["Instagram", "Facebook"]  # Par défaut
        
        footer = homepage_data.get("footer", {})
        footer_text = footer.get("text", "").lower()
        footer_links = footer.get("links", [])
        
        platforms = []
        social_keywords = {
            "instagram": ["instagram", "ig"],
            "facebook": ["facebook", "fb"],
            "twitter": ["twitter", "x"],
            "linkedin": ["linkedin"],
            "youtube": ["youtube", "yt"],
            "tiktok": ["tiktok"]
        }
        
        # Vérifier dans le texte du footer
        for platform, keywords in social_keywords.items():
            if any(keyword in footer_text for keyword in keywords):
                platforms.append(platform.capitalize())
        
        # Vérifier dans les liens du footer
        for link in footer_links:
            link_text = link.get("text", "").lower()
            link_url = link.get("url", "").lower()
            
            for platform, keywords in social_keywords.items():
                if any(keyword in link_text or keyword in link_url for keyword in keywords):
                    if platform.capitalize() not in platforms:
                        platforms.append(platform.capitalize())
        
        return platforms if platforms else ["Instagram", "Facebook"]
    
    def _infer_business_goals(self, industry: str, business_type: str, products: List[Dict]) -> List[str]:
        """Déduit les objectifs business"""
        goals = []
        
        if business_type == "B2C":
            goals.append("Augmenter les ventes en ligne")
            goals.append("Développer la notoriété de marque")
        elif business_type == "B2B":
            goals.append("Générer des leads qualifiés")
            goals.append("Établir l'expertise sectorielle")
        
        if len(products) > 10:
            goals.append("Diversifier l'offre produit")
        
        return goals if goals else ["Développer la présence en ligne", "Augmenter le trafic"]
    
    def _infer_market_position(self, products: List[Dict], homepage_data: Dict) -> str:
        """Déduit la position sur le marché"""
        if not products:
            return "Niche"
        
        # Basé sur le nombre de produits et la gamme de prix
        price_range = self._detect_price_range(products)
        
        if price_range == "Haut de gamme":
            return "Premium"
        elif len(products) > 50:
            return "Leader"
        else:
            return "Spécialiste"
    
    def _generate_tags(self, industry: str, business_type: str, products: List[Dict]) -> List[str]:
        """Génère des tags pour la recherche"""
        tags = [industry, business_type]
        
        if products:
            tags.append("e-commerce")
            price_range = self._detect_price_range(products)
            tags.append(price_range.lower().replace(' ', '_'))
        
        return tags
    
    def _calculate_completeness(self, profile_data: Dict) -> float:
        """Calcule le taux de complétion du profil"""
        required_fields = ['company_name', 'industry', 'business_type']
        filled_fields = 0
        
        for field in required_fields:
            if profile_data.get(field):
                filled_fields += 1
        
        return min(100, (filled_fields / len(required_fields)) * 100)
    
    def get_profile(self, site_id: str) -> Dict[str, Any]:
        """Récupère un profil client par site_id"""
        profile = self.collection.find_one({"site_id": site_id})
        if not profile:
            # Générer le profil s'il n'existe pas
            try:
                profile = self.generate_profile_from_scraped_data(site_id)
            except:
                profile = None
        return profile
    
    def get_all_profiles(self) -> List[Dict[str, Any]]:
        """Récupère tous les profils clients"""
        return list(self.collection.find({}))
    
    def generate_context_prompt(self, site_id: str) -> str:
        """Génère un prompt contextuel basé sur le profil client"""
        profile = self.get_profile(site_id)
        if not profile:
            return ""
        
        context_parts = []
        
        # En-tête du contexte
        context_parts.append(f"# CONTEXTE SITE: {profile['company_name']}")
        
        # Informations de base
        context_parts.append(f"## Profil du Site")
        context_parts.append(f"- **Domaine**: {profile['domain']}")
        context_parts.append(f"- **Industrie**: {profile['industry']}")
        context_parts.append(f"- **Type de Business**: {profile['business_type']}")
        context_parts.append(f"- **Position Marché**: {profile['market_position']}")
        context_parts.append(f"- **Audience Cible**: {', '.join(profile['target_audience']['demographics'])}")
        context_parts.append(f"- **Gamme de Prix**: {profile['target_audience']['price_range']}")
        
        # Identité de marque
        context_parts.append(f"## Identité de Marque")
        context_parts.append(f"- **Voix**: {profile['brand_voice']}")
        context_parts.append(f"- **Valeurs**: {', '.join(profile['brand_values'])}")
        
        # Préférences de contenu
        if profile['content_preferences']:
            context_parts.append(f"## Stratégie de Contenu")
            context_parts.append(f"- **Formats**: {', '.join(profile['content_preferences']['formats'])}")
            context_parts.append(f"- **Thèmes**: {', '.join(profile['content_preferences']['topics'])}")
        
        # Objectifs business
        if profile['business_goals']:
            context_parts.append(f"## Objectifs Business")
            for goal in profile['business_goals'][:3]:
                context_parts.append(f"- {goal}")
        
        # Statistiques du scraping
        if profile.get('scraped_stats'):
            stats = profile['scraped_stats']
            context_parts.append(f"## Données Disponibles")
            context_parts.append(f"- **Pages analysées**: {stats['total_pages']}")
            context_parts.append(f"- **Produits référencés**: {stats['total_products']}")
        
        return "\n".join(context_parts)