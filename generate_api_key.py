#!/usr/bin/env python3
"""
Generate a secure API key for MCP server authentication.
"""

import secrets
import sys

def generate_api_key(length: int = 32) -> str:
    """Generate a secure random API key."""
    return secrets.token_urlsafe(length)

def main():
    print("=" * 60)
    print("MCP Server API Key Generator")
    print("=" * 60)
    print()
    
    # Generate multiple keys
    print("Here are 3 secure API keys (copy one):")
    print()
    
    for i in range(3):
        key = generate_api_key()
        print(f"Key {i+1}: {key}")
    
    print()
    print("=" * 60)
    print("Setup Instructions:")
    print("=" * 60)
    print()
    print("1. Copy one of the keys above")
    print("2. Add to your .env file:")
    print("   API_KEY_ENABLED=true")
    print("   MCP_API_KEY=<paste-key-here>")
    print()
    print("3. Add to Claude Desktop config:")
    print('   "headers": {')
    print('     "Authorization": "Bearer <paste-key-here>"')
    print('   }')
    print()
    print("4. Keep this key secure and never commit it to git!")
    print()

if __name__ == "__main__":
    main()