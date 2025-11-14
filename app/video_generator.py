# video_generator.py - Version corrigée
import os
import requests
import time
import json
import base64
from typing import Dict, List, Optional
import replicate
from dotenv import load_dotenv
load_dotenv()


class VideoGenerator:
    def __init__(self, replicate_api_key: str = None):
        self.replicate_api_key = replicate_api_key or os.getenv("REPLICATE_API_KEY")
        if self.replicate_api_key:
            self.client = replicate.Client(api_token=self.replicate_api_key)
        else:
            self.client = None
        
        # Modèles gratuits
        self.free_models = [
            {
                "name": "Zeroscope Free",
                "id": "anotherjesse/zeroscope-v2-xl:71996d331e8ede697efb8bba5cbfb6cafade79e044a49e22b69c71759cb4a19c",
                "free_tier": True,
            },
            {
                "name": "ModelScope Free", 
                "id": "deepsdk/modelscope-text-to-video:ca5fe2a7d095fdcbd67a4a09f4d07c15ceac5c5c7c6b0d6b4f5b8c1c0c5c5c5c",
                "free_tier": True,
            }
        ]
    
    def test_connection(self) -> Dict:
        """Teste la connexion avec les modèles gratuits"""
        if not self.client:
            return {
                "success": False,
                "error": "❌ Clé API Replicate non configurée"
            }
        
        try:
            model_info = self.client.models.get("anotherjesse/zeroscope-v2-xl")
            return {
                "success": True,
                "message": "✅ Connecté à Replicate (Mode Gratuit)",
                "free_models_available": len(self.free_models)
            }
        except Exception as e:
            return {
                "success": False, 
                "error": f"❌ Erreur de connexion: {str(e)}"
            }

    # MÉTHODE UNIFIÉE - Accepte tous les paramètres
    def generate_product_video(self, 
                             product_image_url: str,
                             client_context: Dict,
                             tone: str,
                             social_media: str,
                             product_description: str = None) -> Dict:
        """
        Méthode principale qui gère à la fois les versions payantes et gratuites
        """
        # Utiliser la version gratuite par défaut
        return self.generate_free_video(
            product_image_url=product_image_url,
            client_context=client_context,
            tone=tone, 
            social_media=social_media,
            product_description=product_description
        )
    
    def generate_free_video(self, 
                          product_image_url: str = None,
                          client_context: Dict = None,
                          tone: str = "professional", 
                          social_media: str = "instagram",
                          product_description: str = None) -> Dict:
        """
        Génère une vidéo avec des modèles gratuits
        Accepte les mêmes paramètres que l'ancienne méthode
        """
        if not self.client:
            return {
                "success": False,
                "error": "❌ Client Replicate non initialisé"
            }
        
        try:
            print("🎬 Génération vidéo gratuite...")
            
            # Construire le prompt à partir des paramètres
            prompt = self._build_video_prompt(
                client_context or {},
                tone, 
                social_media,
                product_description
            )
            
            # Configuration minimale pour économiser
            config = {
                "instagram": {"width": 384, "height": 384, "num_frames": 24, "fps": 12},
                "tiktok": {"width": 320, "height": 560, "num_frames": 30, "fps": 15},
                "facebook": {"width": 384, "height": 384, "num_frames": 24, "fps": 12},
                "youtube": {"width": 448, "height": 252, "num_frames": 24, "fps": 12}
            }.get(social_media, {"width": 384, "height": 384, "num_frames": 24, "fps": 12})
            
            print(f"📝 Prompt utilisé: {prompt}")
            print(f"⚙️ Configuration: {config}")
            
            # Essayer les modèles gratuits dans l'ordre
            for model in self.free_models:
                try:
                    print(f"🔄 Essai avec {model['name']}...")
                    
                    output = self.client.run(
                        model["id"],
                        input={
                            "prompt": prompt,
                            "num_frames": config["num_frames"],
                            "width": config["width"], 
                            "height": config["height"],
                            "fps": config["fps"],
                            "guidance_scale": 12.5,
                            "negative_prompt": "blurry, low quality, distorted, ugly"
                        }
                    )
                    
                    print(f"✅ Succès avec {model['name']}")
                    return {
                        "success": True,
                        "video_url": output[0] if isinstance(output, list) else output,
                        "model_used": model["name"],
                        "cost": "GRATUIT",
                        "quality": "BASSE (mode gratuit)",
                        "duration": f"{config['num_frames']/config['fps']:.1f}s",
                        "platform": social_media,
                        "prompt_used": prompt
                    }
                    
                except Exception as e:
                    print(f"⚠️ {model['name']} échoué: {e}")
                    continue
            
            return {
                "success": False,
                "error": "❌ Tous les modèles gratuits ont échoué. Les serveurs peuvent être surchargés."
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"❌ Erreur génération gratuite: {str(e)}"
            }
    
    def _build_video_prompt(self, 
                          client_context: Dict, 
                          tone: str, 
                          social_media: str,
                          product_description: str) -> str:
        """Construit le prompt pour la génération vidéo"""
        
        tone_mapping = {
            "professional": "professionnel et élégant",
            "casual": "décontracté et amical", 
            "luxury": "luxueux et sophistiqué",
            "playful": "joyeux et énergique",
            "minimalist": "minimaliste et épuré",
            "bold": "audacieux et dynamique"
        }
        
        platform_mapping = {
            "instagram": "format carré Instagram, esthétique soignée",
            "tiktok": "format vertical TikTok, dynamique et accrocheur", 
            "facebook": "format carré Facebook, professionnel",
            "youtube": "format horizontal YouTube, qualité cinématographique"
        }
        
        industry = client_context.get('industry', 'produit')
        brand_voice = client_context.get('brand_voice', '')
        company_name = client_context.get('company_name', '')
        
        prompt_parts = []
        
        if company_name:
            prompt_parts.append(f"Vidéo marketing pour {company_name}")
        if industry:
            prompt_parts.append(f"secteur {industry}")
            
        prompt_parts.extend([
            f"Ton: {tone_mapping.get(tone, 'professionnel')}",
            f"Style: {platform_mapping.get(social_media, 'marketing')}",
        ])
        
        if brand_voice:
            prompt_parts.append(f"Voix de marque: {brand_voice}")
            
        if product_description:
            prompt_parts.append(f"Produit: {product_description}")
        
        # Éléments visuels généraux
        prompt_parts.extend([
            "Haute qualité, éclairage professionnel",
            "Mouvement fluide, transition douce", 
            "Style moderne et attractif"
        ])
        
        return ". ".join(prompt_parts)
    
    def get_available_models(self) -> List[Dict]:
        """Retourne les modèles vidéo disponibles"""
        return [
            {
                "name": "Zeroscope v2 XL (Gratuit)",
                "id": "anotherjesse/zeroscope-v2-xl",
                "description": "Génération vidéo gratuite - qualité basique",
                "max_duration": 2,
                "status": "gratuit"
            },
            {
                "name": "ModelScope (Gratuit)",
                "id": "deepsdk/modelscope-text-to-video", 
                "description": "Alternative gratuite",
                "max_duration": 2,
                "status": "gratuit"
            }
        ]