#!/usr/bin/env python
"""
Script to fix the owner of stddev_breakout strategy or make it available to all users.
"""
import os
from datetime import datetime
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Fix strategy ownership or visibility."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL")
    
    if not database_url:
        print("ERROR: DEV_DATABASE_URL not found in .env")
        return
    
    print(f"Connecting to database...")
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # Get the strategy details
        cursor.execute("""
            SELECT id, name, user_id, description 
            FROM strategy_codes 
            WHERE name = 'stddev_breakout'
        """)
        
        strategy = cursor.fetchone()
        
        if not strategy:
            print("ERROR: stddev_breakout strategy not found")
            return
            
        print(f"\nCurrent strategy details:")
        print(f"  ID: {strategy[0]}")
        print(f"  Name: {strategy[1]}")
        print(f"  Current Owner ID: {strategy[2]}")
        print(f"  Description: {strategy[3]}")
        
        # Get your actual user email
        user_email = input("\nEnter your email address to find your user ID: ").strip()
        
        if user_email:
            # Find user by email
            cursor.execute(
                "SELECT id, email, username FROM users WHERE email = %s",
                (user_email,)
            )
            user = cursor.fetchone()
            
            if user:
                print(f"\nFound user:")
                print(f"  User ID: {user[0]}")
                print(f"  Email: {user[1]}")
                print(f"  Username: {user[2]}")
                
                if user[0] != strategy[2]:
                    # Update strategy owner
                    confirm = input(f"\nChange strategy owner from user {strategy[2]} to user {user[0]}? (y/n): ")
                    
                    if confirm.lower() == 'y':
                        cursor.execute("""
                            UPDATE strategy_codes 
                            SET user_id = %s, updated_at = %s
                            WHERE name = 'stddev_breakout'
                        """, (user[0], datetime.utcnow()))
                        
                        conn.commit()
                        print(f"\nStrategy owner updated to user {user[0]}")
                        print("You should now see it in your 'My Strategies' section!")
                    else:
                        print("\nNo changes made")
                else:
                    print(f"\nYou already own this strategy!")
                    print("Check the 'My Strategies' or 'Strategy Engine' section in the frontend")
            else:
                print(f"\nUser with email '{user_email}' not found")
        
        # Alternative: List all users to choose from
        print("\n" + "="*50)
        print("Alternative: Here are recent active users:")
        cursor.execute("""
            SELECT DISTINCT u.id, u.email, u.username 
            FROM users u
            JOIN broker_accounts ba ON u.id = ba.user_id
            WHERE ba.is_active = true
            ORDER BY u.id
            LIMIT 10
        """)
        
        users = cursor.fetchall()
        for u in users:
            print(f"  User {u[0]}: {u[1]} ({u[2] or 'no username'})")
            
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()