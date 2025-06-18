import re
from typing import Dict, List, Optional

class MessageParser:
    """Parse Slack messages to extract bug report information"""
    
    # Environment mapping
    ENVIRONMENT_KEYWORDS = {
        'prod': 'Prod',
        'production': 'Prod', 
        'live': 'Prod',
        'dev': 'Dev',
        'development': 'Dev',
        'develop': 'Dev',
        'stage': 'Stage',
        'staging': 'Stage',
        'test': 'Stage',
        'testing': 'Stage'
    }
    
    # Product mapping  
    PRODUCT_KEYWORDS = {
        'dataloader': 'Dataloader AI',
        'data loader': 'Dataloader AI',
        'data-loader': 'Dataloader AI',
        'clientell': 'Clientell AI',
        'client-ell': 'Clientell AI',
        'ai': 'Clientell AI',
        'other': 'Other'
    }
    
    DEFAULT_ENVIRONMENT = 'Prod'
    DEFAULT_PRODUCT = 'Clientell AI'
    
    @classmethod
    def parse_message(cls, text: str) -> Dict:
        """
        Parse message content to extract all bug report information
        
        Returns:
            Dict containing:
            - title: Bug title/summary
            - description: Bug description
            - environment: Detected environment 
            - product: Detected product
            - urls: Detected URLs (share_urls, chat_urls)
        """
        if not text:
            return cls._empty_result()
        
        # Extract URLs first
        urls = cls.extract_urls(text)
        
        # Detect environment and product
        environment = cls.detect_environment(text)
        product = cls.detect_product(text)
        
        # Split title and description
        title, description = cls.split_title_description(text)
        
        return {
            'title': title,
            'description': description,
            'environment': environment,
            'product': product,
            'urls': urls,
            'original_text': text
        }
    
    @classmethod
    def detect_environment(cls, text: str) -> str:
        """Detect environment from text content"""
        if not text:
            return cls.DEFAULT_ENVIRONMENT
        
        text_lower = text.lower()
        
        # Look for environment keywords
        for keyword, env_value in cls.ENVIRONMENT_KEYWORDS.items():
            if keyword in text_lower:
                return env_value
        
        return cls.DEFAULT_ENVIRONMENT
    
    @classmethod
    def detect_product(cls, text: str) -> str:
        """Detect product from text content"""
        if not text:
            return cls.DEFAULT_PRODUCT
        
        text_lower = text.lower()
        
        # Look for product keywords
        for keyword, product_value in cls.PRODUCT_KEYWORDS.items():
            if keyword in text_lower:
                return product_value
        
        return cls.DEFAULT_PRODUCT
    
    @classmethod
    def split_title_description(cls, text: str) -> tuple:
        """
        Split message into title and description
        - Use first sentence (until first full stop) as title
        - If no full stop, use first 255 characters as title
        - Rest becomes description
        """
        if not text:
            return "", ""
        
        # Clean up the text
        text = text.strip()
        
        # Look for first full stop
        full_stop_match = re.search(r'\.(?:\s|$)', text)
        
        if full_stop_match:
            # Split at first full stop
            split_index = full_stop_match.start() + 1
            title = text[:split_index-1].strip()  # Remove the full stop
            description = text[split_index:].strip()
        else:
            # No full stop found, use first 255 characters
            if len(text) <= 255:
                title = text
                description = ""
            else:
                title = text[:255].strip()
                description = text[255:].strip()
        
        # Clean up title - remove any leading/trailing punctuation
        title = title.strip('.,!?;: ')
        
        # Ensure title is not empty
        if not title and description:
            # If title is empty but description exists, take first line of description
            lines = description.split('\n')
            title = lines[0][:100] if lines[0] else "Bug Report"
            description = '\n'.join(lines[1:]) if len(lines) > 1 else ""
        
        # Fallback if both are empty
        if not title:
            title = "Bug Report"
        
        return title, description
    
    @classmethod
    def extract_urls(cls, text: str) -> Dict[str, List[str]]:
        """Extract and categorize URLs from text"""
        if not text:
            return {'share_urls': [], 'chat_urls': []}
        
        # Patterns for different URL types
        share_patterns = [
            r'https://app\.clientell\.ai/share/[a-f0-9-]+',
            r'https://dev\.clientell\.ai/share/[a-f0-9-]+',
            r'https://test\.clientell\.ai/share/[a-f0-9-]+'
        ]
        
        chat_patterns = [
            r'https://app\.clientell\.ai/chat/[a-f0-9-]+',
            r'https://dev\.clientell\.ai/chat/[a-f0-9-]+',
            r'https://test\.clientell\.ai/chat/[a-f0-9-]+'
        ]
        
        share_urls = []
        chat_urls = []
        
        # Find share URLs
        for pattern in share_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            share_urls.extend(matches)
        
        # Find chat URLs  
        for pattern in chat_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            chat_urls.extend(matches)
        
        return {
            'share_urls': list(set(share_urls)),  # Remove duplicates
            'chat_urls': list(set(chat_urls))
        }
    
    @classmethod
    def validate_share_url(cls, url: str) -> bool:
        """Validate if URL is a proper share URL format"""
        if not url:
            return False
        
        share_patterns = [
            r'https://app\.clientell\.ai/share/[a-f0-9-]+',
            r'https://dev\.clientell\.ai/share/[a-f0-9-]+',
            r'https://test\.clientell\.ai/share/[a-f0-9-]+'
        ]
        
        for pattern in share_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return True
        return False
    
    @classmethod
    def _empty_result(cls) -> Dict:
        """Return empty parsing result"""
        return {
            'title': 'Bug Report',
            'description': '',
            'environment': cls.DEFAULT_ENVIRONMENT,
            'product': cls.DEFAULT_PRODUCT,
            'urls': {'share_urls': [], 'chat_urls': []},
            'original_text': ''
        }

# Test the parser
if __name__ == "__main__":
    # Test cases
    test_messages = [
        "Login not working in prod environment https://app.clientell.ai/share/123-456",
        "The dataloader is crashing. Here's the chat: https://app.clientell.ai/chat/abc-def", 
        "Clientell AI dashboard showing wrong data in staging",
        "This is a very long message that exceeds the 255 character limit. Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. And this should be in the description part.",
        "Short bug. And this is the description."
    ]
    
    for msg in test_messages:
        result = MessageParser.parse_message(msg)
        print(f"Message: {msg[:50]}...")
        print(f"Title: {result['title']}")
        print(f"Description: {result['description'][:50]}...")
        print(f"Environment: {result['environment']}")
        print(f"Product: {result['product']}")
        print(f"URLs: {result['urls']}")
        print("-" * 80)