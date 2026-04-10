#!/usr/bin/env python3
"""
Infrastructure Testing Script
Tests connectivity to Supabase and RabbitMQ
"""

import os
import sys
import pika
from supabase import create_client
from dotenv import load_dotenv

def test_supabase_connection():
    """Test Supabase connectivity"""
    print("🔍 Testing Supabase connection...")
    
    try:
        # Load environment variables
        load_dotenv()
        
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        
        if not supabase_url or not supabase_key:
            print("❌ Supabase credentials not found in .env file")
            return False
        
        # Create Supabase client
        supabase = create_client(supabase_url, supabase_key)
        
        # Test query - try to select 1 row from scraping_jobs
        result = supabase.table('scraping_jobs').select('id').limit(1).execute()
        
        print("✅ Supabase connection successful")
        return True
        
    except Exception as e:
        print(f"❌ Supabase connection failed: {str(e)}")
        return False

def test_rabbitmq_connection():
    """Test RabbitMQ connectivity"""
    print("🔍 Testing RabbitMQ connection...")
    
    try:
        # Load environment variables
        load_dotenv()
        
        rabbitmq_url = os.getenv('RABBITMQ_URL', 'amqp://localhost:5672')
        
        # Connect to RabbitMQ
        connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        channel = connection.channel()
        
        # Create test queue
        test_queue = 'test_infra_queue'
        channel.queue_declare(queue=test_queue, durable=True)
        
        # Send test message
        channel.basic_publish(
            exchange='',
            routing_key=test_queue,
            body='Test message',
            properties=pika.BasicProperties(delivery_mode=2)  # make message persistent
        )
        
        # Clean up
        channel.queue_delete(queue=test_queue)
        connection.close()
        
        print("✅ RabbitMQ connection successful")
        return True
        
    except Exception as e:
        print(f"❌ RabbitMQ connection failed: {str(e)}")
        return False

def main():
    """Main test function"""
    print("🚀 Starting Infrastructure Tests\n")
    
    # Test both services
    supabase_ok = test_supabase_connection()
    rabbitmq_ok = test_rabbitmq_connection()
    
    print("\n" + "="*50)
    
    if supabase_ok and rabbitmq_ok:
        print("✅ Infrastructure Ready")
        return 0
    else:
        print("❌ Infrastructure Not Ready")
        return 1

if __name__ == "__main__":
    sys.exit(main())
