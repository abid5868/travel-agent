"""
main.py - Minimal CLI Interface for Dynamic Travel Replanning Agent

Usage:
    python main.py --task benchmarks/tasks/easy/easy1.json
    python main.py --task benchmarks/tasks/easy/easy1.json --verbose
"""

import json
import argparse
import os
from pathlib import Path
from typing import Dict, Any

from src.agent import TravelAgent


def load_task(task_path: str) -> Dict[str, Any]:
    """Load a task specification from JSON file"""
    with open(task_path, 'r') as f:
        return json.load(f)


def print_separator(char="=", length=70):
    """Print a separator line"""
    print(char * length)


def print_task_info(task: Dict[str, Any]):
    """Print task information"""
    print_separator()
    print(f"TASK: {task['title']}")
    print_separator()
    print(f"Difficulty: {task['difficulty'].upper()}")
    print(f"Origin: {task['scenario']['origin_city']}")
    print(f"Destinations: {', '.join(task['scenario']['destination_cities'])}")
    print(f"Duration: {task['scenario']['trip_duration_days']} days")
    
    # Print hard constraints
    print("\nHard Constraints:")
    hard = task['initial_constraints']['hard']
    for key, value in hard.items():
        if value:
            print(f"  • {key}: {value}")
    
    # Print interests
    if task['initial_constraints']['soft'].get('interests'):
        print("\nInterests:")
        for interest in task['initial_constraints']['soft']['interests']:
            print(f"  • {interest}")
    
    print_separator()


def print_results(result: Dict[str, Any], verbose: bool = False):
    """Print the agent's output"""
    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)
    
    # Print itinerary
    print("\nFinal Itinerary:")
    if isinstance(result.get('itinerary'), str):
        print(result['itinerary'])
    else:
        print(json.dumps(result.get('itinerary', {}), indent=2))
    
    # Print validation
    print("\nValidation:")
    if 'validation' in result:
        is_valid, errors = result['validation']
        if is_valid:
            print("  ✓ All constraints satisfied")
        else:
            print("  ✗ Constraint violations:")
            for error in errors:
                print(f"    - {error}")
    
    # Print metadata
    if 'metadata' in result:
        meta = result['metadata']
        print(f"\nMetadata:")
        print(f"  • Total tokens: {meta.get('total_tokens', 'N/A')}")
        print(f"  • API calls: {meta.get('api_calls', 'N/A')}")
        print(f"  • Tool calls: {meta.get('tool_calls', 'N/A')}")
        print(f"  • Time elapsed: {meta.get('time_elapsed', 'N/A')}s")
    
    # Print conversation history if verbose
    if verbose and 'conversation' in result:
        print("\n" + "="*70)
        print("CONVERSATION HISTORY")
        print("="*70)
        for i, msg in enumerate(result['conversation'], 1):
            role = msg['role'].upper()
            content = msg['content']
            print(f"\n[{i}] {role}:")
            print(content)
    
    print_separator()


def run_task(task_path: str, verbose: bool = False):
    """Run agent on a single task"""
    # Check if task exists
    if not os.path.exists(task_path):
        print(f"Error: Task file not found: {task_path}")
        return
    
    # Load task
    print("Loading task...")
    task = load_task(task_path)
    print_task_info(task)
    
    # Get API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nError: ANTHROPIC_API_KEY environment variable not set")
        print("Set it with: export ANTHROPIC_API_KEY=your_key_here")
        return
    
    # Initialize agent
    print("\nInitializing agent...")
    try:
        agent = TravelAgent(api_key=api_key)
        print("Agent ready")
    except Exception as e:
        print(f"Error initializing agent: {e}")
        return
    
    # Run planning
    print("\nStarting planning...\n")
    try:
        result = agent.plan_trip(task)
        print_results(result, verbose=verbose)
        
        # Save results
        output_dir = Path("results/test_runs")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{task['task_id']}_output.json"
        
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)
        
        print(f"\nResults saved to: {output_path}")
        
    except Exception as e:
        print(f"\nError during planning: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Dynamic Travel Replanning Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--task',
        type=str,
        required=True,
        help='Path to task JSON file'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output including conversation history'
    )
    
    args = parser.parse_args()
    
    run_task(args.task, verbose=args.verbose)


if __name__ == "__main__":
    main()