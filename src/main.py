"""
main.py - CLI Interface for Dynamic Travel Replanning Agent

Usage:
    python main.py --task benchmarks/tasks/easy/task_001.json
    python main.py --task benchmarks/tasks/easy/task_001.json --verbosex
"""

import json
import argparse
import os
from pathlib import Path
from typing import Dict, Any

# Import your agent (you'll build this)
from src.agent import TravelAgent


def load_task(task_path: str) -> Dict[str, Any]:
    """Load a task specification from JSON file"""
    with open(task_path, 'r') as f:
        task = json.load(f)
    return task


def print_separator(char="=", length=70):
    """Print a separator line"""
    print(char * length)


def print_task_info(task: Dict[str, Any]):
    """Print task information in a readable format"""
    print_separator()
    print(f"TASK: {task['title']}")
    print_separator()
    print(f"\nDifficulty: {task['difficulty'].upper()}")
    print(f"Origin: {task['scenario']['origin_city']}")
    print(f"Destinations: {', '.join(task['scenario']['destination_cities'])}")
    print(f"Duration: {task['scenario']['trip_duration_days']} days")
    print(f"Party Size: {task['user_profile']['party_size']}")
    
    # Print hard constraints
    print("\n📋 Hard Constraints:")
    hard = task['initial_constraints']['hard']
    for key, value in hard.items():
        if value:  # Only print non-empty values
            print(f"  • {key}: {value}")
    
    # Print soft preferences
    if task['initial_constraints']['soft'].get('interests'):
        print("\n💭 Interests:")
        for interest in task['initial_constraints']['soft']['interests']:
            print(f"  • {interest}")
    
    # Print dynamic events if any
    if task.get('dynamic_events') and len(task['dynamic_events']) > 0:
        print(f"\n⚠️  Dynamic Events: {len(task['dynamic_events'])} event(s) will occur")
    
    print_separator()


def print_itinerary(result: Dict[str, Any], verbose: bool = False):
    """Print the agent's output in a readable format"""
    print("\n" + "="*70)
    print("AGENT OUTPUT")
    print("="*70)
    
    if verbose:
        # Print full conversation history
        print("\n📝 Conversation History:")
        if 'conversation' in result:
            for i, msg in enumerate(result['conversation'], 1):
                role = msg['role'].upper()
                content = msg['content'][:200] + "..." if len(msg['content']) > 200 else msg['content']
                print(f"\n[{i}] {role}:")
                print(f"  {content}")
    
    # Print final itinerary
    print("\n✈️  Final Itinerary:")
    if isinstance(result.get('itinerary'), str):
        print(result['itinerary'])
    else:
        print(json.dumps(result.get('itinerary', {}), indent=2))
    
    # Print validation results
    print("\n✅ Validation Results:")
    if 'validation' in result:
        is_valid, errors = result['validation']
        if is_valid:
            print("  ✓ All constraints satisfied!")
        else:
            print("  ✗ Constraint violations detected:")
            for error in errors:
                print(f"    - {error}")
    
    # Print metadata
    if verbose and 'metadata' in result:
        print("\n📊 Metadata:")
        metadata = result['metadata']
        print(f"  • Total tokens: {metadata.get('total_tokens', 'N/A')}")
        print(f"  • API calls: {metadata.get('api_calls', 'N/A')}")
        print(f"  • Time elapsed: {metadata.get('time_elapsed', 'N/A')}s")
    
    print_separator()


def run_single_task(task_path: str, verbose: bool = False):
    """Run agent on a single task"""
    # Check if task file exists
    if not os.path.exists(task_path):
        print(f"❌ Error: Task file not found: {task_path}")
        return
    
    # Load task
    print("📂 Loading task...")
    task = load_task(task_path)
    print_task_info(task)
    
    # Initialize agent
    print("\n🤖 Initializing agent...")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ Error: ANTHROPIC_API_KEY environment variable not set")
        print("   Please set it: export ANTHROPIC_API_KEY=your_key_here")
        return
    
    try:
        agent = TravelAgent(api_key=api_key)
        print("✓ Agent initialized")
    except Exception as e:
        print(f"❌ Error initializing agent: {e}")
        return
    
    # Run planning
    print("\n🚀 Starting planning...\n")
    try:
        result = agent.plan_trip(task)
        print_itinerary(result, verbose=verbose)
        
        # Save results
        output_dir = Path("results/test_runs")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{task['task_id']}_output.json"
        
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)
        
        print(f"\n💾 Results saved to: {output_path}")
        
    except Exception as e:
        print(f"\n❌ Error during planning: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


def interactive_mode():
    """Interactive mode for testing agent conversationally"""
    print_separator()
    print("INTERACTIVE MODE")
    print_separator()
    print("\nEnter trip details and the agent will help you plan.")
    print("Type 'quit' to exit.\n")
    
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ Error: ANTHROPIC_API_KEY environment variable not set")
        return
    
    try:
        agent = TravelAgent(api_key=api_key)
        print("✓ Agent ready\n")
    except Exception as e:
        print(f"❌ Error initializing agent: {e}")
        return
    
    # Simple interactive loop
    print("Where would you like to go?")
    origin = input("Origin city: ").strip()
    destination = input("Destination city: ").strip()
    budget = input("Budget (USD): ").strip()
    days = input("Number of days: ").strip()
    
    # Create a simple task
    simple_task = {
        "task_id": "interactive_001",
        "difficulty": "easy",
        "title": f"Trip from {origin} to {destination}",
        "scenario": {
            "origin_city": origin,
            "destination_cities": [destination],
            "trip_duration_days": int(days) if days.isdigit() else 3
        },
        "user_profile": {
            "party_size": 1,
            "traveler_types": ["leisure"]
        },
        "initial_constraints": {
            "hard": {
                "budget_max": int(budget) if budget.isdigit() else 1000,
                "departure_date": "2026-07-01",
                "return_date": "2026-07-04"
            },
            "soft": {
                "interests": ["sightseeing"],
                "preferences": []
            }
        },
        "dynamic_events": [],
        "required_components": []
    }
    
    print("\n🚀 Planning your trip...\n")
    try:
        result = agent.plan_trip(simple_task)
        print_itinerary(result, verbose=False)
    except Exception as e:
        print(f"\n❌ Error: {e}")


def list_available_tasks():
    """List all available benchmark tasks"""
    print_separator()
    print("AVAILABLE BENCHMARK TASKS")
    print_separator()
    
    tasks_dir = Path("benchmarks/tasks")
    if not tasks_dir.exists():
        print("\n❌ No tasks directory found at benchmarks/tasks/")
        return
    
    for difficulty in ['easy', 'medium', 'hard']:
        difficulty_dir = tasks_dir / difficulty
        if difficulty_dir.exists():
            tasks = sorted(difficulty_dir.glob("*.json"))
            if tasks:
                print(f"\n{difficulty.upper()} ({len(tasks)} tasks):")
                for task_path in tasks:
                    # Load and show title
                    try:
                        with open(task_path, 'r') as f:
                            task = json.load(f)
                        print(f"  • {task_path.name:<30} {task.get('title', 'Untitled')}")
                    except:
                        print(f"  • {task_path.name:<30} (error loading)")
    
    print_separator()


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Dynamic Travel Replanning Agent - CLI Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --task benchmarks/tasks/easy/task_001.json
  python main.py --task benchmarks/tasks/medium/task_007.json --verbose
  python main.py --list
  python main.py --interactive
        """
    )
    
    parser.add_argument(
        '--task',
        type=str,
        help='Path to task JSON file'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output including conversation history'
    )
    
    parser.add_argument(
        '--interactive', '-i',
        action='store_true',
        help='Run in interactive mode'
    )
    
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='List all available benchmark tasks'
    )
    
    args = parser.parse_args()
    
    # Handle different modes
    if args.list:
        list_available_tasks()
    elif args.interactive:
        interactive_mode()
    elif args.task:
        run_single_task(args.task, verbose=args.verbose)
    else:
        parser.print_help()
        print("\n💡 Tip: Start with --list to see available tasks")


if __name__ == "__main__":
    main()