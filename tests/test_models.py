"""
Unit tests for models.py - Pydantic validation models.
"""
import pytest
from pydantic import ValidationError
from models import (
    LLMDecision,
    BatchLLMRequest,
    BatchLLMResponse,
    ArticleInput
)


class TestLLMDecision:
    """Test LLM decision validation."""
    
    def test_valid_llm_decision(self):
        """Test valid LLM decision passes validation."""
        decision = LLMDecision(
            relevant=True,
            reason="Valid apartment listing",
            floor=3,
            street="Andrássy út",
            building_type="tégla",
            property_category="lakás",
            has_terrace=False
        )
        assert decision.relevant is True
        assert decision.floor == 3
    
    def test_llm_decision_missing_required_fields(self):
        """Test validation fails without required fields."""
        with pytest.raises(ValidationError):
            LLMDecision(relevant=True)  # Missing 'reason'
    
    def test_llm_decision_optional_fields(self):
        """Test optional fields can be None."""
        decision = LLMDecision(
            relevant=False,
            reason="Not a residential property",
            floor=None,
            street=None,
            building_type=None,
            property_category=None,
            has_terrace=None
        )
        assert decision.relevant is False
        assert decision.floor is None
    
    def test_llm_decision_type_coercion(self):
        """Test type coercion for floor."""
        decision = LLMDecision(
            relevant=True,
            reason="Test",
            floor="5"  # String should be converted to int
        )
        assert decision.floor == 5
        assert isinstance(decision.floor, int)


class TestBatchLLMRequest:
    """Test batch LLM request validation."""
    
    def test_valid_batch_request(self, sample_article_data):
        """Test valid batch request."""
        request = BatchLLMRequest(
            articles=[
                ArticleInput(**sample_article_data),
                ArticleInput(**{**sample_article_data, 'article_id': 'TEST_002'})
            ]
        )
        assert len(request.articles) == 2
    
    def test_empty_batch_request(self):
        """Test empty batch is allowed."""
        request = BatchLLMRequest(articles=[])
        assert len(request.articles) == 0


class TestArticleInput:
    """Test article input validation."""
    
    def test_valid_article_input(self, sample_article_data):
        """Test valid article data."""
        article = ArticleInput(**sample_article_data)
        assert article.article_id == 'TEST_001'
        assert article.area == 65
        assert article.price == 45000000
    
    def test_article_missing_required_field(self):
        """Test validation fails without required fields."""
        with pytest.raises(ValidationError):
            ArticleInput(
                article_id='TEST_001',
                title='Test'
                # Missing other required fields
            )
    
    def test_article_type_validation(self, sample_article_data):
        """Test type validation for numeric fields."""
        with pytest.raises(ValidationError):
            ArticleInput(**{**sample_article_data, 'price': 'not_a_number'})
        
        with pytest.raises(ValidationError):
            ArticleInput(**{**sample_article_data, 'area': 'not_a_number'})


class TestBatchLLMResponse:
    """Test batch LLM response validation."""
    
    def test_valid_batch_response(self):
        """Test valid batch response with decisions."""
        response = BatchLLMResponse(
            decisions=[
                LLMDecision(
                    relevant=True,
                    reason="Valid",
                    floor=3,
                    property_category="lakás"
                ),
                LLMDecision(
                    relevant=False,
                    reason="Invalid",
                    floor=None
                )
            ]
        )
        assert len(response.decisions) == 2
        assert response.decisions[0].relevant is True
        assert response.decisions[1].relevant is False


class TestDataSanitization:
    """Test input sanitization and edge cases."""
    
    def test_xss_protection_in_strings(self, sample_article_data):
        """Test that HTML/script tags are handled."""
        malicious_data = {
            **sample_article_data,
            'title': '<script>alert("xss")</script>Test',
            'description': '<img src=x onerror=alert(1)>Desc'
        }
        article = ArticleInput(**malicious_data)
        # Pydantic accepts strings as-is, sanitization should happen in processing
        assert '<script>' in article.title  # Raw data preserved, sanitize later
    
    def test_extremely_long_strings(self, sample_article_data):
        """Test handling of very long text fields."""
        long_desc = "A" * 100000  # 100k chars
        article = ArticleInput(**{**sample_article_data, 'description': long_desc})
        assert len(article.description) == 100000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
