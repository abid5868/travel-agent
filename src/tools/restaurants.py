"""
Mock Data Generator for Travel Planning Benchmark
==================================================

This script generates realistic mock data for:
- Flights between 10 US cities, and some international cities
- Hotels in each city (budget, mid-range, luxury)
- Restaurants (various cuisines)
- Activities (tours, attractions)

Usage:
    python scripts/generate_mock_data.py

Output:
    benchmarks/mock_data/flights.json
    benchmarks/mock_data/hotels.json
    benchmarks/mock_data/restaurants.json
    benchmarks/mock_data/activities.json
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path


# Configuration
CITIES = [
    "Chicago",
    "New York",
    "Los Angeles",
    "San Francisco",
    "Seattle",
    "Denver",
    "Austin",
    "Miami",
    "Boston",
    "Nashville"
]

# City coordinates for distance calculations (approximate)
CITY_COORDS = {
    "Chicago": (41.8781, -87.6298),
    "New York": (40.7128, -74.0060),
    "Los Angeles": (34.0522, -118.2437),
    "San Francisco": (37.7749, -122.4194),
    "Seattle": (47.6062, -122.3321),
    "Denver": (39.7392, -104.9903),
    "Austin": (30.2672, -97.7431),
    "Miami": (25.7617, -80.1918),
    "Boston": (42.3601, -71.0589),
    "Nashville": (36.1627, -86.7816)
}

AIRLINES = ["United", "American", "Delta", "Southwest", "JetBlue", "Alaska"]

CUISINES = [
    "American",
    "Italian", 
    "Mexican",
    "Asian",
    "Chinese",
    "Japanese",
    "Thai",
    "BBQ",
    "Seafood",
    "Steakhouse",
    "French",
    "Mediterranean"
]

ACTIVITY_TYPES = [
    "Museum",
    "Tour",
    "Outdoor",
    "Music Venue",
    "Theater",
    "Sports",
    "Shopping",
    "Park",
    "Historical Site",
    "Art Gallery"
]

