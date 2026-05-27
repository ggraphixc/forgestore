"""Modern Product Review System — System 8"""
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from app.models import Review, ReviewMedia, ReviewReaction, ReviewSentiment, ReviewModeration, Product, User

logger = logging.getLogger("forgestore.review")


class ReviewService:
    """Handles product review creation, media, reactions, and retailer replies."""

    def __init__(self, db: Session):
        self.db = db

    def create_review(self, product_id: str, user_id: str, author: str, rating: int,
                      title: Optional[str] = None, content: Optional[str] = None) -> Review:
        """Create a new product review."""
        review = Review(
            product_id=product_id,
            user_id=user_id,
            author=author,
            rating=rating,
            title=title,
            content=content,
        )
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)

        # Update product rating
        self._update_product_rating(product_id)

        # Queue AI moderation
        from app.services.review_service import ReviewModerationService
        mod_service = ReviewModerationService(self.db)
        mod_service.queue_moderation(review.id)

        # Queue sentiment analysis
        if content:
            from app.services.review_service import SentimentService
            sentiment_service = SentimentService(self.db)
            sentiment_service.analyze_sentiment(review.id, content)

        return review

    def add_media(self, review_id: str, media_type: str, url: str,
                  thumbnail_url: Optional[str] = None, is_cover: bool = False) -> ReviewMedia:
        """Add media to a review."""
        media = ReviewMedia(
            review_id=review_id,
            media_type=media_type,
            url=url,
            thumbnail_url=thumbnail_url,
            is_cover=is_cover,
        )
        self.db.add(media)
        self.db.commit()
        self.db.refresh(media)
        return media

    def react_to_review(self, review_id: str, user_id: str, reaction_type: str) -> ReviewReaction:
        """Add or toggle a reaction on a review."""
        existing = self.db.query(ReviewReaction).filter(
            ReviewReaction.review_id == review_id,
            ReviewReaction.user_id == user_id,
            ReviewReaction.reaction_type == reaction_type,
        ).first()

        if existing:
            # Toggle off
            self.db.delete(existing)
            self.db.commit()
            review = self.db.query(Review).filter(Review.id == review_id).first()
            if review:
                review.helpful = max(0, review.helpful - 1)
                self.db.commit()
            return None

        reaction = ReviewReaction(
            review_id=review_id,
            user_id=user_id,
            reaction_type=reaction_type,
        )
        self.db.add(reaction)
        self.db.commit()

        # Increment helpful count
        review = self.db.query(Review).filter(Review.id == review_id).first()
        if review and reaction_type == "helpful":
            review.helpful = (review.helpful or 0) + 1
            self.db.commit()

        self.db.refresh(reaction)
        return reaction

    def add_retailer_reply(self, review_id: str, reply_content: str) -> Review:
        """Add a retailer reply to a review (stored in review content as reply)."""
        review = self.db.query(Review).filter(Review.id == review_id).first()
        if not review:
            raise ValueError("Review not found")

        # Append reply to content
        current = review.content or ""
        review.content = f"{current}\n\n--- Retailer Reply ---\n{reply_content}"
        self.db.commit()
        self.db.refresh(review)
        return review

    def get_product_reviews(self, product_id: str, sort: str = "newest",
                            rating_filter: Optional[int] = None,
                            media_only: bool = False,
                            limit: int = 20, offset: int = 0) -> list[Review]:
        """Get reviews for a product with filtering and sorting."""
        query = self.db.query(Review).filter(Review.product_id == product_id)

        if rating_filter:
            query = query.filter(Review.rating == rating_filter)
        if media_only:
            query = query.filter(Review.media.any())

        if sort == "newest":
            query = query.order_by(Review.created_at.desc())
        elif sort == "oldest":
            query = query.order_by(Review.created_at.asc())
        elif sort == "highest":
            query = query.order_by(Review.rating.desc())
        elif sort == "lowest":
            query = query.order_by(Review.rating.asc())
        elif sort == "helpful":
            query = query.order_by(Review.helpful.desc())

        return query.offset(offset).limit(limit).all()

    def _update_product_rating(self, product_id: str):
        """Recalculate and update product rating."""
        reviews = self.db.query(Review).filter(Review.product_id == product_id).all()
        if reviews:
            avg_rating = sum(r.rating for r in reviews) / len(reviews)
            self.db.query(Product).filter(Product.id == product_id).update({
                "rating": round(avg_rating, 1),
                "review_count": len(reviews),
            })
            self.db.commit()


class ReviewModerationService:
    """AI-powered review moderation pipeline."""

    def __init__(self, db: Session):
        self.db = db

    def queue_moderation(self, review_id: str):
        """Queue a review for AI moderation."""
        moderation = ReviewModeration(
            review_id=review_id,
            status="PENDING",
        )
        self.db.add(moderation)
        self.db.commit()

        # Auto-moderate with simple heuristics
        self._auto_moderate(review_id)

    def _auto_moderate(self, review_id: str):
        """Basic content moderation heuristics."""
        review = self.db.query(Review).filter(Review.id == review_id).first()
        if not review or not review.content:
            self._set_moderation_status(review_id, "APPROVED", "No content to moderate")
            return

        content = review.content.lower()
        flags = []

        # Check for spam patterns
        spam_patterns = ["buy now", "click here", "http://", "https://", "free money", "subscribe"]
        for pattern in spam_patterns:
            if pattern in content:
                flags.append({"type": "spam", "pattern": pattern, "confidence": 0.8})

        # Check for offensive content
        offensive_words = ["spam_word_1", "spam_word_2"]  # Would use a proper list in production
        for word in offensive_words:
            if word in content:
                flags.append({"type": "offensive", "pattern": word, "confidence": 0.9})

        # Check for fake review patterns
        fake_patterns = ["this product is", "i bought this", "the seller"]
        fake_count = sum(1 for p in fake_patterns if p in content)
        if fake_count >= 3:
            flags.append({"type": "fake", "pattern": "generic template", "confidence": 0.5})

        if flags:
            self._set_moderation_status(review_id, "FLAGGED", "AI moderation flags", flags)
        else:
            self._set_moderation_status(review_id, "APPROVED", "Passed auto-moderation")

    def _set_moderation_status(self, review_id: str, status: str, reason: str, ai_flags: Optional[list] = None):
        """Update moderation status."""
        self.db.query(ReviewModeration).filter(
            ReviewModeration.review_id == review_id
        ).update({
            "status": status,
            "reason": reason,
            "ai_flags": ai_flags or [],
        })
        self.db.commit()

    def approve_review(self, review_id: str, admin_id: str, notes: Optional[str] = None):
        """Manually approve a review."""
        self.db.query(ReviewModeration).filter(
            ReviewModeration.review_id == review_id
        ).update({
            "status": "APPROVED",
            "reviewed_by": admin_id,
            "reviewed_at": datetime.utcnow(),
            "notes": notes,
        })
        self.db.commit()

    def reject_review(self, review_id: str, admin_id: str, reason: str, notes: Optional[str] = None):
        """Reject a review."""
        self.db.query(ReviewModeration).filter(
            ReviewModeration.review_id == review_id
        ).update({
            "status": "REJECTED",
            "reason": reason,
            "reviewed_by": admin_id,
            "reviewed_at": datetime.utcnow(),
            "notes": notes,
        })
        self.db.commit()


class SentimentService:
    """Sentiment analysis for product reviews."""

    def __init__(self, db: Session):
        self.db = db

    def analyze_sentiment(self, review_id: str, content: str):
        """Analyze sentiment of a review using heuristics/lexicon-based approach."""
        if not content:
            return

        # Simple lexicon-based sentiment analysis
        positive_words = {"excellent", "amazing", "great", "love", "perfect", "wonderful",
                         "fantastic", "awesome", "best", "beautiful", "impressive", "happy",
                         "satisfied", "recommend", "superb", "outstanding", "brilliant"}
        negative_words = {"terrible", "awful", "worst", "hate", "horrible", "poor",
                         "disappointed", "bad", "broken", "defective", "useless", "frustrating",
                         "waste", "return", "damaged", "cheap", "fake", "scam"}

        words = set(content.lower().split())
        positive_count = len(words & positive_words)
        negative_count = len(words & negative_words)
        total = positive_count + negative_count

        if total == 0:
            sentiment = "neutral"
            score = 0.0
        else:
            score = (positive_count - negative_count) / total
            if score > 0.3:
                sentiment = "positive"
            elif score < -0.3:
                sentiment = "negative"
            else:
                sentiment = "neutral"

        # Extract keywords
        from collections import Counter
        word_freq = Counter(w.lower() for w in content.split() if len(w) > 3)
        keywords = [w for w, _ in word_freq.most_common(5)]

        existing = self.db.query(ReviewSentiment).filter(
            ReviewSentiment.review_id == review_id
        ).first()

        if existing:
            existing.sentiment = sentiment
            existing.score = score
            existing.keywords = keywords
        else:
            sentiment_obj = ReviewSentiment(
                review_id=review_id,
                sentiment=sentiment,
                score=score,
                keywords=keywords,
            )
            self.db.add(sentiment_obj)

        self.db.commit()
