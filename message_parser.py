import re
from typing import Dict, List, Optional

import re
from typing import Dict, List, Optional, Any

class MessageParser:
    """Parse Slack messages to extract bug report information including attachments"""
    
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
    
    # Supported attachment types for Jira
    SUPPORTED_IMAGE_TYPES = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'webp'}
    SUPPORTED_VIDEO_TYPES = {'mp4', 'mov', 'avi', 'mkv', 'webm', 'flv'}
    SUPPORTED_DOCUMENT_TYPES = {'pdf', 'doc', 'docx', 'txt', 'csv', 'xlsx', 'xls'}
    
    DEFAULT_ENVIRONMENT = 'Prod'
    DEFAULT_PRODUCT = 'Clientell AI'
    
    @classmethod
    def parse_message(cls, text: str, slack_event: Dict = None) -> Dict:
        """
        Parse message content to extract all bug report information including attachments
        
        Args:
            text: Message text content
            slack_event: Full Slack event data (contains file information)
        
        Returns:
            Dict containing:
            - title: Bug title/summary
            - description: Bug description
            - environment: Detected environment 
            - product: Detected product
            - urls: Detected URLs (share_urls, chat_urls)
            - attachments: File attachments (files, images, videos, documents)
        """
        if not text:
            text = ""
        
        # Extract URLs from text
        urls = cls.extract_urls(text)
        
        # Extract attachments from Slack event
        attachments = cls.extract_attachments(slack_event) if slack_event else cls._empty_attachments()
        
        # Detect environment and product
        environment = cls.detect_environment(text)
        product = cls.detect_product(text)
        
        # Split title and description
        title, description = cls.split_title_description(text)
        
        # If we have attachments but no text, create a meaningful title
        if not text.strip() and attachments['files']:
            title = f"Bug report with {len(attachments['files'])} attachment(s)"
        
        return {
            'title': title,
            'description': description,
            'environment': environment,
            'product': product,
            'urls': urls,
            'attachments': attachments,
            'original_text': text
        }
    
    @classmethod
    def extract_attachments(cls, slack_event: Dict) -> Dict[str, List[Dict]]:
        """
        Extract attachment information from Slack event
        
        Args:
            slack_event: The full Slack event containing file information
            
        Returns:
            Dict with categorized attachments:
            - files: All files with metadata
            - images: Image files only
            - videos: Video files only  
            - documents: Document files only
        """
        if not slack_event:
            return cls._empty_attachments()
        
        files = slack_event.get('files', [])
        if not files:
            return cls._empty_attachments()
        
        all_files = []
        images = []
        videos = []
        documents = []
        
        for file_info in files:
            # Extract file metadata
            file_data = {
                'id': file_info.get('id'),
                'name': file_info.get('name', 'unknown'),
                'title': file_info.get('title', ''),
                'mimetype': file_info.get('mimetype', ''),
                'filetype': file_info.get('filetype', '').lower(),
                'size': file_info.get('size', 0),
                'url_private': file_info.get('url_private', ''),
                'url_private_download': file_info.get('url_private_download', ''),
                'permalink': file_info.get('permalink', ''),
                'permalink_public': file_info.get('permalink_public', ''),
                'thumb_url': file_info.get('thumb_360', file_info.get('thumb_160', '')),
                'is_external': file_info.get('is_external', False),
                'external_type': file_info.get('external_type', ''),
                'external_url': file_info.get('external_url', ''),
                'created': file_info.get('created', 0),
                'user': file_info.get('user', ''),
                'username': file_info.get('username', ''),
                'channels': file_info.get('channels', []),
                'is_public': file_info.get('is_public', False)
            }
            
            all_files.append(file_data)
            
            # Categorize by file type
            filetype = file_data['filetype']
            
            if filetype in cls.SUPPORTED_IMAGE_TYPES:
                images.append(file_data)
            elif filetype in cls.SUPPORTED_VIDEO_TYPES:
                videos.append(file_data)
            elif filetype in cls.SUPPORTED_DOCUMENT_TYPES:
                documents.append(file_data)
        
        return {
            'files': all_files,
            'images': images,
            'videos': videos,
            'documents': documents,
            'count': len(all_files)
        }
    
    @classmethod
    def get_attachment_summary(cls, attachments: Dict) -> str:
        """
        Generate a summary string for attachments
        
        Args:
            attachments: Attachments dict from extract_attachments
            
        Returns:
            Human readable summary string
        """
        if not attachments or not attachments.get('files'):
            return "No attachments"
        
        total = attachments['count']
        images = len(attachments['images'])
        videos = len(attachments['videos']) 
        documents = len(attachments['documents'])
        other = total - images - videos - documents
        
        parts = []
        if images > 0:
            parts.append(f"{images} image{'s' if images != 1 else ''}")
        if videos > 0:
            parts.append(f"{videos} video{'s' if videos != 1 else ''}")
        if documents > 0:
            parts.append(f"{documents} document{'s' if documents != 1 else ''}")
        if other > 0:
            parts.append(f"{other} other file{'s' if other != 1 else ''}")
        
        return f"{total} attachment{'s' if total != 1 else ''}: " + ", ".join(parts)
    
    @classmethod
    def validate_attachment_for_jira(cls, file_data: Dict) -> Dict[str, Any]:
        """
        Validate if attachment can be uploaded to Jira
        
        Args:
            file_data: Single file data dict
            
        Returns:
            Dict with validation results:
            - valid: bool
            - reason: str (if not valid)
            - jira_compatible: bool
            - size_ok: bool
            - type_supported: bool
        """
        # Jira attachment limits (these are typical - adjust based on your Jira config)
        MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
        
        size_ok = file_data.get('size', 0) <= MAX_FILE_SIZE
        filetype = file_data.get('filetype', '').lower()
        
        # Check if file type is supported
        type_supported = (
            filetype in cls.SUPPORTED_IMAGE_TYPES or
            filetype in cls.SUPPORTED_VIDEO_TYPES or
            filetype in cls.SUPPORTED_DOCUMENT_TYPES
        )
        
        # Check if file is accessible (not external or has proper URLs)
        has_download_url = bool(
            file_data.get('url_private_download') or 
            file_data.get('url_private') or
            file_data.get('external_url')
        )
        
        valid = size_ok and type_supported and has_download_url
        
        reasons = []
        if not size_ok:
            reasons.append(f"File too large ({file_data.get('size', 0)} bytes > {MAX_FILE_SIZE})")
        if not type_supported:
            reasons.append(f"Unsupported file type: {filetype}")
        if not has_download_url:
            reasons.append("No accessible download URL")
        
        return {
            'valid': valid,
            'reason': "; ".join(reasons) if reasons else "File is valid for Jira upload",
            'jira_compatible': valid,
            'size_ok': size_ok,
            'type_supported': type_supported,
            'has_download_url': has_download_url,
            'file_name': file_data.get('name', 'unknown'),
            'file_size': file_data.get('size', 0),
            'file_type': filetype
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
            'attachments': cls._empty_attachments(),
            'original_text': ''
        }
    
    @classmethod
    def _empty_attachments(cls) -> Dict:
        """Return empty attachments structure"""
        return {
            'files': [],
            'images': [],
            'videos': [],
            'documents': [],
            'count': 0
        }

# Test the parser
if __name__ == "__main__":
    # Test cases including file attachments
    test_messages = [
        ("Login not working in prod environment https://app.clientell.ai/share/123-456", None),
        ("The dataloader is crashing. Here's the chat: https://app.clientell.ai/chat/abc-def", None),
        ("Screenshot attached showing the error", {
            'files': [{
                'id': 'F123456',
                'name': 'error_screenshot.png',
                'title': 'Error Screenshot',
                'mimetype': 'image/png',
                'filetype': 'png',
                'size': 1024000,
                'url_private': 'https://files.slack.com/files-pri/T123/F123456/error_screenshot.png',
                'url_private_download': 'https://files.slack.com/files-pri/T123/F123456/download/error_screenshot.png',
                'permalink': 'https://clientell.slack.com/files/U123/F123456/error_screenshot.png',
                'thumb_360': 'https://files.slack.com/files-tmb/T123/F123456/error_screenshot_360.png',
                'created': 1640995200,
                'user': 'U123456',
                'is_public': False
            }]
        })
    ]
    
    print("=" * 80)
    print("MESSAGE PARSER TESTS WITH ATTACHMENTS")
    print("=" * 80)
    
    for i, (msg, slack_event) in enumerate(test_messages, 1):
        print(f"\n--- Test Case {i} ---")
        result = MessageParser.parse_message(msg, slack_event)
        
        print(f"Message: {msg}")
        print(f"Title: {result['title']}")
        print(f"Description: {result['description'][:50]}{'...' if len(result['description']) > 50 else ''}")
        print(f"Environment: {result['environment']}")
        print(f"Product: {result['product']}")
        print(f"URLs: {result['urls']}")
        print(f"Attachments: {MessageParser.get_attachment_summary(result['attachments'])}")
        
        # Show attachment details if present
        if result['attachments']['files']:
            print("Attachment Details:")
            for file_data in result['attachments']['files']:
                validation = MessageParser.validate_attachment_for_jira(file_data)
                print(f"  - {file_data['name']} ({file_data['filetype']}, {file_data['size']} bytes)")
                print(f"    Jira Compatible: {validation['jira_compatible']} - {validation['reason']}")
        
        print("-" * 80)