import requests
import json
from typing import Dict, List, Optional, Any
import os
from fractions import Fraction

class SportsBettingAPI:
    def __init__(self, api_token: str):
        """
        Initialize the Sports Betting API client
        
        Args:
            api_token: API token for B365 API access
        """
        self.api_token = api_token
        self.base_url = "http://api.b365api.com"
        
        # Sport IDs mapping (from the PHP code)
        self.sports = {
            'soccer': 1,
            'basketball': 18,
            'tennis': 13,
            'volleyball': 91,
            'handball': 78,
            'baseball': 16,
            'ice_hockey': 17,
            'snooker': 14,
            'american_football': 12,
            'cricket': 3,
            'futsal': 83,
            'darts': 15,
            'table_tennis': 92,
            'badminton': 94,
            'rugby_union': 8,
            'rugby_league': 19,
            'australian_rules': 36,
            'bowls': 66,
            'boxing_ufc': 9,
            'gaelic_sports': 75,
            'floorball': 90,
            'beach_volleyball': 95,
            'water_polo': 110,
            'squash': 107,
            'esports': 151
        }

    def convert_to_decimal(self, fraction_str: str) -> float:
        """
        Convert fractional odds to decimal format
        
        Args:
            fraction_str: Fractional odds string (e.g., "5/2")
            
        Returns:
            Decimal odds as float
        """
        try:
            if '/' in fraction_str:
                numerator, denominator = fraction_str.split('/')
                decimal_value = float(numerator) / float(denominator)
                return round(decimal_value, 2)
            else:
                return float(fraction_str)
        except (ValueError, ZeroDivisionError):
            return 0.0

    def get_inplay_events(self, sport: str, limit: int = 10, group_by_league: bool = False) -> Dict[str, Any]:
        """
        Get in-play events for a specific sport
        
        Args:
            sport: Sport name (tennis, handball, basketball)
            limit: Number of events to fetch (default: 10, 'all' for all events)
            group_by_league: Whether to group results by league
            
        Returns:
            Dictionary containing match data
        """
        if sport not in self.sports:
            return {"error": f"Sport '{sport}' not supported"}
        
        sport_id = self.sports[sport]
        
        # Special handling for soccer (if needed in the future)
        if sport_id == 1:
            return self._get_soccer_inplay_events(limit, group_by_league)
        
        # For other sports, use the API
        url = f"{self.base_url}/v1/bet365/inplay_filter"
        params = {
            'sport_id': sport_id,
            'token': self.api_token
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            api_data = response.json()
            
            if 'results' not in api_data:
                return {"error": "No results found in API response"}
            
            # Limit results if specified
            if limit == 'all':
                data = api_data['results']
            else:
                data = api_data['results'][:limit]
            
            # Process each match to get odds
            processed_data = []
            league_matches = {}
            
            for index, match in enumerate(data):
                match_with_odds = self._get_match_odds(match, sport_id)
                
                # Only include matches with odds
                if match_with_odds.get('odds'):
                    if group_by_league:
                        league_id = match['league']['id']
                        league_name = match['league']['name']
                        
                        if league_id not in league_matches:
                            league_matches[league_id] = {
                                'name': league_name,
                                'matches': []
                            }
                        league_matches[league_id]['matches'].append(match_with_odds)
                    else:
                        processed_data.append(match_with_odds)
            
            return league_matches if group_by_league else processed_data
            
        except requests.exceptions.RequestException as e:
            return {"error": f"API request failed: {str(e)}"}
        except json.JSONDecodeError as e:
            return {"error": f"Failed to parse API response: {str(e)}"}

    def _get_match_odds(self, match: Dict, sport_id: int) -> Dict:
        """Get odds for a specific match based on sport type"""
        match_copy = match.copy()
        
        if sport_id == 1:  # Soccer
            match_copy['odds'] = self._get_soccer_odds(match['id'])
        elif sport_id == 13:  # Tennis
            match_copy['odds'] = self._get_tennis_odds(match['id'])
        else:  # Other sports (Basketball, Handball, etc.)
            match_copy['odds'] = self._get_generic_odds(match['id'])
        
        return match_copy

    def _get_soccer_odds(self, event_id: str) -> List[Dict]:
        """Get soccer-specific odds (fulltime result)"""
        url = f"{self.base_url}/v1/bet365/event"
        params = {
            'token': self.api_token,
            'FI': event_id
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if 'results' not in data or not data['results']:
                return []
            
            odds = []
            columns = 0
            market_found = False
            
            for result in data['results'][0]:
                # Look for fulltime result market (ID: 1777)
                if result.get('type') == 'MG' and result.get('ID') == 1777:
                    market_found = True
                
                if market_found and result.get('type') == 'MA':
                    columns = result.get('CN', 0)
                
                if columns > 0 and market_found and result.get('type') == 'PA':
                    odds.append({
                        'title': result.get('NA', ''),
                        'name': result.get('N2', ''),
                        'odds': self.convert_to_decimal(result.get('OD', '0')) + 1
                    })
                    columns -= 1
                    if columns == 0:
                        market_found = False
            
            return odds
            
        except Exception as e:
            print(f"Error fetching soccer odds: {e}")
            return []

    def _get_tennis_odds(self, event_id: str) -> List[Dict]:
        """Get tennis-specific odds (to win match)"""
        url = f"{self.base_url}/v3/bet365/prematch"
        params = {
            'token': self.api_token,
            'FI': event_id
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if 'results' not in data or not data['results']:
                return []
            
            # Extract to_win_match odds if available
            main_odds = data['results'][0].get('main', {}).get('sp', {}).get('to_win_match', {}).get('odds', [])
            return main_odds if main_odds else []
            
        except Exception as e:
            print(f"Error fetching tennis odds: {e}")
            return []

    def _get_generic_odds(self, event_id: str) -> List[Dict]:
        """Get generic odds for other sports"""
        url = f"{self.base_url}/v3/bet365/prematch"
        params = {
            'token': self.api_token,
            'FI': event_id
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if 'results' not in data or not data['results']:
                return []
            
            return data['results'][0]
            
        except Exception as e:
            print(f"Error fetching generic odds: {e}")
            return []

    def _get_soccer_inplay_events(self, limit: int, group_by_league: bool) -> Dict:
        """Special handling for soccer in-play events (if using local database)"""
        # This would be implemented if you have a local database like in the PHP code
        # For now, we'll use the API approach
        return self.get_inplay_events('soccer', limit, group_by_league)

    def get_featured_games(self, sport: str, limit: int = 15) -> List[Dict]:
        """
        Get featured upcoming games for a sport
        
        Args:
            sport: Sport name
            limit: Number of games to fetch
            
        Returns:
            List of featured games with odds
        """
        if sport not in self.sports:
            return []
        
        sport_id = self.sports[sport]
        
        from datetime import datetime
        today = datetime.now().strftime('%Y%m%d')
        
        url = f"{self.base_url}/v1/bet365/upcoming"
        params = {
            'sport_id': sport_id,
            'token': self.api_token,
            'day': today
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            api_data = response.json()
            
            if 'results' not in api_data:
                return []
            
            data = api_data['results'][:limit]
            featured_games = []
            
            for match in data:
                match_with_odds = self._get_match_odds(match, sport_id)
                if match_with_odds.get('odds'):
                    featured_games.append(match_with_odds)
            
            return featured_games
            
        except Exception as e:
            print(f"Error fetching featured games: {e}")
            return []

    def get_prematch_odds(self, event_id: str, sport: str) -> Dict:
        """
        Get detailed prematch odds for a specific event
        
        Args:
            event_id: Event ID
            sport: Sport name
            
        Returns:
            Dictionary containing detailed odds
        """
        if sport not in self.sports:
            return {}
        
        sport_id = self.sports[sport]
        
        if sport_id == 1:  # Soccer - detailed odds
            return self._get_detailed_soccer_odds(event_id)
        else:  # Other sports
            url = f"{self.base_url}/v1/bet365/prematch"
            params = {
                'FI': event_id,
                'token': self.api_token
            }
            
            try:
                response = requests.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                return data.get('results', {})
            except Exception as e:
                print(f"Error fetching prematch odds: {e}")
                return {}

    def _get_detailed_soccer_odds(self, event_id: str) -> Dict:
        """Get detailed soccer odds including multiple markets"""
        url = f"{self.base_url}/v1/bet365/event"
        params = {
            'token': self.api_token,
            'FI': event_id
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if 'results' not in data or not data['results']:
                return {}
            
            odds = {}
            
            # Market IDs and their processing
            markets = {
                1777: 'fulltime_result',
                10115: 'double_chance',
                10161: 'half_time_result',
                1778: 'first_goal',
                421: 'match_goals'
            }
            
            for market_id, market_name in markets.items():
                odds[market_name] = self._extract_market_odds(data['results'][0], market_id, market_name)
            
            return odds
            
        except Exception as e:
            print(f"Error fetching detailed soccer odds: {e}")
            return {}

    def _extract_market_odds(self, results: List, market_id: int, market_name: str) -> List[Dict]:
        """Extract odds for a specific market"""
        market_odds = []
        columns = 0
        market_found = False
        
        for result in results:
            if result.get('type') == 'MG' and result.get('ID') == market_id:
                market_found = True
            
            if market_found and result.get('type') == 'MA':
                columns = result.get('CN', 0)
            
            if columns > 0 and market_found and result.get('type') == 'PA':
                if market_name == 'match_goals' and 'HA' in result:
                    market_odds.append({
                        'handicap': result.get('HA'),
                        'odds': self.convert_to_decimal(result.get('OD', '0')) + 1
                    })
                    if len(market_odds) >= 2:
                        market_found = False
                else:
                    market_odds.append({
                        'title': result.get('NA', ''),
                        'name': result.get('N2', ''),
                        'odds': self.convert_to_decimal(result.get('OD', '0')) + 1
                    })
                    columns -= 1
                    if columns == 0:
                        market_found = False
        
        return market_odds


    def save_to_json(self, data: Any, filename: str) -> bool:
        """
        Save data to JSON file
        
        Args:
            data: Data to save
            filename: Name of the JSON file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving to {filename}: {e}")
            return False

    def fetch_and_save_all_sports(self, limit: int = 10, save_featured: bool = True) -> Dict[str, str]:
        """
        Fetch data for tennis, handball, and basketball and save to JSON files
        
        Args:
            limit: Number of matches to fetch per sport
            save_featured: Whether to also save featured games
            
        Returns:
            Dictionary with status of each save operation
        """
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results = {}
        
        # Sports to fetch
        target_sports = ['tennis', 'handball', 'basketball']
        
        for sport in target_sports:
            print(f"Fetching {sport.upper()} matches...")
            
            # Fetch in-play matches
            matches = self.get_inplay_events(sport, limit=limit)
            
            # Create comprehensive data structure
            sport_data = {
                'sport': sport,
                'sport_id': self.sports[sport],
                'timestamp': datetime.now().isoformat(),
                'total_matches': len(matches) if isinstance(matches, list) else 0,
                'inplay_matches': matches,
                'featured_games': [],
                'status': 'success' if isinstance(matches, list) else 'error'
            }
            
            # Add error info if applicable
            if isinstance(matches, dict) and 'error' in matches:
                sport_data['error'] = matches['error']
            
            # Fetch featured games if requested and in-play was successful
            if save_featured and isinstance(matches, list):
                print(f"Fetching featured {sport} games...")
                featured = self.get_featured_games(sport, limit=5)
                sport_data['featured_games'] = featured
                sport_data['total_featured'] = len(featured)
            
            # Save to JSON file
            filename = f"{sport}_matches_{timestamp}.json"
            if self.save_to_json(sport_data, filename):
                results[sport] = f"Saved to {filename}"
                print(f"✓ {sport.capitalize()} data saved to {filename}")
            else:
                results[sport] = f"Failed to save {filename}"
                print(f"✗ Failed to save {sport} data")
        
        # Save combined data
        combined_data = {
            'timestamp': datetime.now().isoformat(),
            'sports_data': {}
        }
        
        # Read back the individual files to create combined
        for sport in target_sports:
            filename = f"{sport}_matches_{timestamp}.json"
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    combined_data['sports_data'][sport] = json.load(f)
            except Exception as e:
                print(f"Error reading {filename} for combined data: {e}")
        
        combined_filename = f"all_sports_matches_{timestamp}.json"
        if self.save_to_json(combined_data, combined_filename):
            results['combined'] = f"Combined data saved to {combined_filename}"
            print(f"✓ Combined data saved to {combined_filename}")
        else:
            results['combined'] = "Failed to save combined data"
            print("✗ Failed to save combined data")
        
        return results


# Example usage
def main():
    # Initialize the API client
    # Replace 'YOUR_API_TOKEN' with your actual API token
    api_token = os.getenv('API_TOKEN', '215845-ME7THuixJ1hOxE')
    
    if api_token == 'YOUR_API_TOKEN':
        print("⚠️  Please set your API token in the API_TOKEN environment variable or modify the code.")
        print("Example: export API_TOKEN='your_actual_token_here'")
        return
    
    api = SportsBettingAPI(api_token)
    
    # Fetch and save all sports data
    print("🏀 Starting to fetch sports betting data...")
    print("=" * 60)
    
    results = api.fetch_and_save_all_sports(limit=10, save_featured=True)
    
    print("\n" + "=" * 60)
    print("📊 SUMMARY OF OPERATIONS:")
    print("=" * 60)
    
    for sport, status in results.items():
        print(f"{sport.capitalize()}: {status}")
    
    print("\n📁 JSON files created in the current directory:")
    import glob
    json_files = glob.glob("*_matches_*.json")
    for file in sorted(json_files):
        print(f"  • {file}")
    
    # Display sample data from one of the files
    if json_files:
        print(f"\n📖 Sample data from {json_files[0]}:")
        try:
            with open(json_files[0], 'r', encoding='utf-8') as f:
                sample_data = json.load(f)
                print(f"Sport: {sample_data.get('sport', 'Unknown')}")
                print(f"Total matches: {sample_data.get('total_matches', 0)}")
                print(f"Status: {sample_data.get('status', 'Unknown')}")
                
                if sample_data.get('inplay_matches') and isinstance(sample_data['inplay_matches'], list):
                    if len(sample_data['inplay_matches']) > 0:
                        match = sample_data['inplay_matches'][0]
                        print(f"Sample match: {match.get('home', {}).get('name', 'Unknown')} vs {match.get('away', {}).get('name', 'Unknown')}")
                        print(f"League: {match.get('league', {}).get('name', 'Unknown')}")
        except Exception as e:
            print(f"Error reading sample data: {e}")


def quick_fetch_and_display():
    """Quick function to fetch and display data without saving"""
    api_token = os.getenv('API_TOKEN', 'YOUR_API_TOKEN')
    api = SportsBettingAPI(api_token)
    
    sports = ['tennis', 'handball', 'basketball']
    
    for sport in sports:
        print(f"\n=== {sport.upper()} IN-PLAY MATCHES ===")
        matches = api.get_inplay_events(sport, limit=3)
        
        if isinstance(matches, list):
            for i, match in enumerate(matches, 1):
                print(f"{i}. {match.get('home', {}).get('name', 'Unknown')} vs {match.get('away', {}).get('name', 'Unknown')}")
                print(f"   League: {match.get('league', {}).get('name', 'Unknown')}")
                print(f"   Time: {match.get('time', 'Unknown')}")
                if match.get('odds'):
                    print(f"   Odds available: Yes")
                print("-" * 40)
        else:
            print(f"Error: {matches}")


# Helper function to read saved JSON data
def read_saved_data(filename: str) -> Dict:
    """
    Read data from a saved JSON file
    
    Args:
        filename: Name of the JSON file to read
        
    Returns:
        Dictionary containing the saved data
    """
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"File {filename} not found")
        return {}
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON from {filename}: {e}")
        return {}
    except Exception as e:
        print(f"Error reading {filename}: {e}")
        return {}


if __name__ == "__main__":
    main()