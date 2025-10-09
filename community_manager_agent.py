import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any
import random

class CommunityManagerAgent:
    """Agent IA spécialisé en Community Management"""
    
    def __init__(self, rag_system):
        self.rag_system = rag_system
        self.platform_strategies = {
            'instagram': {
                'best_times': ['9:00', '12:00', '17:00', '19:00', '21:00'],
                'content_types': ['Posts visuels', 'Stories', 'Reels', 'Carrousels'],
                'hashtag_strategy': '3-5 hashtags niche + 2-3 hashtags populaires'
            },
            'facebook': {
                'best_times': ['8:00', '13:00', '18:00', '20:00'],
                'content_types': ['Posts liens', 'Vidéos', 'Polls', 'Events'],
                'engagement_tips': 'Poser des questions pour booster les commentaires'
            },
            'twitter': {
                'best_times': ['7:00', '12:00', '16:00', '19:00'],
                'content_types': ['Threads', 'Tweets courts', 'Médias', 'Spaces'],
                'frequency': '3-5 tweets par jour minimum'
            },
            'tiktok': {
                'best_times': ['9:00', '12:00', '17:00', '21:00'],
                'content_types': ['Tendances', 'Tutoriels', 'Behind the scenes'],
                'viral_tips': 'Musiques tendance + premiers secondes accrocheuses'
            },
            'linkedin': {
                'best_times': ['8:00', '12:00', '17:00'],
                'content_types': ['Articles longs', 'Posts professionnels', 'Carrousels'],
                'tone': 'Professionnel et value-adding'
            }
        }
        
        # Thèmes pour varier le contenu
        self.daily_themes = [
            "Découverte produit", "Promotion spéciale", "Témoignage client", 
            "Éducation produit", "Behind the scenes", "Question communauté",
            "Flash promotion", "Conseil d'expert", "Nouveauté", "Best-seller"
        ]
    
    def _get_daily_theme(self, day_offset: int) -> str:
        """Retourne un thème quotidien varié"""
        theme_index = day_offset % len(self.daily_themes)
        return self.daily_themes[theme_index]
    
    def _get_varied_time_slots(self, day_offset: int) -> List:
        """Retourne des créneaux horaires variés selon le jour"""
        platforms = ['instagram', 'facebook', 'twitter', 'tiktok', 'linkedin']
        
        # Faire varier les plateformes selon le jour
        day_platforms = platforms[(day_offset % 3):] + platforms[:(day_offset % 3)]
        day_platforms = day_platforms[:3]  # 3 posts par jour
        
        time_slots = []
        base_times = ['9:00', '12:30', '17:00', '19:30', '21:00']
        
        for i, platform in enumerate(day_platforms):
            if i < len(base_times):
                time_slots.append((platform, base_times[i]))
        
        return time_slots
    
    def _generate_daily_post(self, platform: str, promoted_products: List, normal_products: List, day: int, weekday: str) -> Dict:
        """Génère un post quotidien"""
        # Alterner entre produits promus et normaux
        if day % 2 == 0 and promoted_products:
            product = random.choice(promoted_products)
            post_type = "PROMOTION"
        elif normal_products:
            product = random.choice(normal_products)
            post_type = "EDUCATION"
        else:
            product = None
            post_type = "ENGAGEMENT"
        
        # Gérer les descriptions vides ou courtes
        product_description = ""
        if product and product.get('description'):
            desc = product['description']
            if len(desc) > 50:
                product_description = desc[:50] + "..."
            else:
                product_description = desc
        
        content_templates = {
            'instagram': [
                f"✨ {product['name'] if product and product.get('name') else 'Découverte du jour'} ✨\n\n{product_description if product_description else 'Notre sélection spéciale pour vous!'}\n\n👆 Tapotez pour en savoir plus!",
                f"🚀 {weekday} spécial! {product['name'] if product and product.get('name') else 'Notre nouveauté'}\n\n{product.get('price', '') if product and product.get('price') else 'Promotion exclusive'}"
            ],
            'facebook': [
                f"📢 {product['name'] if product and product.get('name') else 'Actualité importante'}\n\n{product_description if product_description else 'Ne manquez pas cette opportunité unique!'}",
                f"🎯 Votre avis compte! Que pensez-vous de {product['name'] if product and product.get('name') else 'notre nouvelle collection'}?"
            ],
            'twitter': [
                f"🔥 {product['name'] if product and product.get('name') else 'Nouveauté'} | {product.get('price', 'Prix spécial') if product else 'Découvrez maintenant!'}\n\n#promo #nouveauté",
                f"💡 Le saviez-vous? {product['name'] if product and product.get('name') else 'Nos produits'} sont {random.choice(['incroyables', 'uniques', 'innovants'])}!"
            ],
            'tiktok': [
                f"🎬 Découvrez {product['name'] if product and product.get('name') else 'notre univers'} en vidéo!\n\n{product_description if product_description else 'Likez si vous aimez 👇'}",
                f"⚡ {product['name'] if product and product.get('name') else 'Trending now'} - {product.get('price', 'Prix choc') if product else 'Limited time!'}"
            ],
            'linkedin': [
                f"💼 {product['name'] if product and product.get('name') else 'Solution professionnelle'}\n\n{product_description if product_description else 'Découvrez comment cela peut booster votre business.'}",
                f"📈 Insights: {product['name'] if product and product.get('name') else 'Notre offre'} - {random.choice(['Efficacité prouvée', 'ROI garanti', 'Solution innovante'])}"
            ]
        }
        
        # Fallback si la plateforme n'est pas trouvée
        templates = content_templates.get(platform, ['📱 Contenu engageant à découvrir sur nos réseaux!'])
        template = random.choice(templates)
        
        return {
            'content': template,
            'type': post_type,
            'goal': 'Engagement' if day % 3 == 0 else 'Conversion'
        }
    
    def _generate_strategy_overview(self, promoted_products: List, normal_products: List, duration_days: int) -> str:
        """Génère un aperçu stratégique"""
        strategy = f"STRATÉGIE DE CONTENU SUR {duration_days} JOURS\n\n"
        strategy += f"• Produits promus à mettre en avant: {len(promoted_products)}\n"
        strategy += f"• Produits catalogue: {len(normal_products)}\n"
        strategy += "• Approche: Mix de contenu éducatif, promotionnel et engageant\n"
        strategy += "• Objectif: Accroître la notoriété et générer des leads qualifiés\n"
        strategy += f"• Thèmes variés: {', '.join(self.daily_themes[:5])}...\n"
        
        return strategy
    
    def _generate_daily_schedule(self, promoted_products: List, normal_products: List, duration_days: int) -> Dict:
        """Génère un planning quotidien varié"""
        schedule = {}
        start_date = datetime.now()
        
        for day in range(duration_days):
            current_date = start_date + timedelta(days=day)
            date_str = current_date.strftime("%Y-%m-%d")
            weekday = current_date.strftime("%A")
            
            # Varier les créneaux horaires
            time_slots = self._get_varied_time_slots(day)
            
            daily_posts = []
            for platform, time_slot in time_slots:
                post = self._generate_daily_post(
                    platform, promoted_products, normal_products, day, weekday
                )
                daily_posts.append({
                    'platform': platform,
                    'time': time_slot,
                    'content': post['content'],
                    'type': post['type'],
                    'goal': post['goal']
                })
            
            schedule[date_str] = {
                'weekday': weekday,
                'posts': daily_posts,
                'theme': self._get_daily_theme(day)
            }
        
        return schedule
    
    def _generate_content_ideas(self, promoted_products: List, normal_products: List) -> List[str]:
        """Génère des idées de contenu"""
        ideas = []
        
        # Idées basées sur les produits promus
        for product in promoted_products[:3]:
            product_name = product.get('name', 'Produit')
            if len(product_name) > 30:  # Limiter la longueur du nom
                product_name = product_name[:30] + "..."
            ideas.append(f"📢 CAMPAGNE PROMO: {product_name} - Mettre en avant les {random.choice(['avantages', 'prix attractif', 'qualité'])}")
        
        # Idées basées sur les produits normaux
        for product in normal_products[:3]:
            product_name = product.get('name', 'produit')
            if len(product_name) > 30:
                product_name = product_name[:30] + "..."
            ideas.append(f"💡 CONTENU ÉDUCATIF: Tutoriel utilisation {product_name} - {random.choice(['conseils', 'astuces', 'bonnes pratiques'])}")
        
        # Idées génériques
        generic_ideas = [
            "🎬 VIDÉO: Behind the scenes de notre entreprise",
            "📊 INFOGRAPHIE: Chiffres clés et statistiques",
            "🤔 SONDAGE: Préférences de la communauté",
            "👥 TÉMOIGNAGE: Avis client mis en avant",
            "🎁 CONCOURS: Jeu concours pour booster l'engagement",
            "📖 GUIDE: Guide d'utilisation de nos produits",
            "🌟 TOP 5: Nos produits les plus populaires",
            "🔄 COMPARAISON: Avantages vs concurrents"
        ]
        
        ideas.extend(generic_ideas)
        return ideas
    
    def _generate_hashtag_strategy(self, products_data: List[Dict]) -> Dict:
        """Génère une stratégie de hashtags"""
        # Extraire les catégories des produits
        categories = set()
        for product in products_data:
            name = product.get('name', '').lower()
            if 'phone' in name or 'iphone' in name or 'samsung' in name:
                categories.add('tech')
            if 'fashion' in name or 'vetement' in name or 'style' in name:
                categories.add('fashion')
            if 'home' in name or 'maison' in name or 'deco' in name:
                categories.add('home')
        
        hashtag_strategies = {
            'tech': ['#tech', '#innovation', '#gadget', '#digital'],
            'fashion': ['#fashion', '#style', '#mode', '#trendy'],
            'home': ['#home', '#deco', '#interieur', '#design'],
            'general': ['#promo', '#nouveauté', '#decouverte', '#bonplan']
        }
        
        strategy = {}
        for category in categories:
            strategy[category] = hashtag_strategies.get(category, [])
        
        strategy['general'] = hashtag_strategies['general']
        return strategy
    
    def _generate_performance_metrics(self) -> Dict:
        """Génère des métriques de performance"""
        return {
            'engagement_rate': '2-5% (cible)',
            'reach_goal': '+15% par semaine',
            'conversion_rate': '3-7% (cible)',
            'content_mix': '40% éducation, 30% promotion, 30% engagement',
            'kpis': ['Likes', 'Partages', 'Commentaires', 'Clics']
        }
    
    def generate_content_calendar(self, products_data: List[Dict], duration_days: int = 7) -> Dict:
        """Génère un calendrier de contenu unique basé sur les produits"""
        calendar = {
            'strategy_overview': '',
            'daily_schedule': {},
            'content_ideas': [],
            'hashtag_strategy': {},
            'performance_metrics': {}
        }
        
        # Analyser les produits pour le contenu
        promoted_products = [p for p in products_data if p.get('is_promoted')]
        normal_products = [p for p in products_data if not p.get('is_promoted')]
        
        # Générer la stratégie
        calendar['strategy_overview'] = self._generate_strategy_overview(
            promoted_products, normal_products, duration_days
        )
        
        # Générer le planning quotidien
        calendar['daily_schedule'] = self._generate_daily_schedule(
            promoted_products, normal_products, duration_days
        )
        
        # Idées de contenu
        calendar['content_ideas'] = self._generate_content_ideas(
            promoted_products, normal_products
        )
        
        # Stratégie de hashtags
        calendar['hashtag_strategy'] = self._generate_hashtag_strategy(products_data)
        
        # Métriques de performance
        calendar['performance_metrics'] = self._generate_performance_metrics()
        
        return calendar