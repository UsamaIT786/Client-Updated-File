import asyncio
import logging
from datetime import datetime, timedelta, UTC
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
import pytz

from winplay import SportsBettingAPI
from database import Match, get_db, SessionLocal
import env_config

logger = logging.getLogger(__name__)

class OddsTracker:
    def __init__(self):
        self.api = SportsBettingAPI(env_config.API_TOKEN)
        self.monitored_sports = ['tennis', 'basketball', 'handball']
        self.live_matches_created = 0
        self.last_summary_time = datetime.now(UTC)
        
    def parse_scores(self, scores_data) -> Tuple[int, int]:
        """Parse scores from different API formats (dict or string)"""
        if isinstance(scores_data, dict):
            try:
                home_score = int(scores_data.get('home', 0)) if scores_data.get('home') is not None else 0
                away_score = int(scores_data.get('away', 0)) if scores_data.get('away') is not None else 0
                return home_score, away_score
            except (ValueError, TypeError):
                return 0, 0
        
        elif isinstance(scores_data, str):
            try:
                # Handle formats like "1-0", "2:1", "1 - 0", etc.
                if '-' in scores_data:
                    home_str, away_str = scores_data.split('-', 1)
                elif ':' in scores_data:
                    home_str, away_str = scores_data.split(':', 1)
                elif ' ' in scores_data and len(scores_data.split()) == 2:
                    home_str, away_str = scores_data.split()
                else:
                    return 0, 0
                
                home_score = int(home_str.strip())
                away_score = int(away_str.strip())
                return home_score, away_score
            except (ValueError, AttributeError, IndexError):
                return 0, 0
        
        # For any other type (list, None, etc.)
        return 0, 0

    def get_pre_match_favorite(self, home_odds: float, away_odds: float) -> str:
        """Determine the favorite based on pre-match odds (lower odds = favorite)"""
        if home_odds < away_odds:
            return 'home'
        return 'away'
    
    def parse_match_time(self, match_data: Dict) -> Dict:
        """Parse match time information to determine current status"""
        # Based on the API documentation about calculating soccer minutes
        time_info = match_data.get('time', {})
        
        # Validate time_info structure
        if not isinstance(time_info, dict):
            time_info = {}
        
        # TT - playing or on break
        # TM - passed minutes
        # TS - passed seconds
        # TU - kicking off time
        
        is_playing = time_info.get('TT', False)
        
        try:
            passed_minutes = int(time_info.get('TM', 0))
            passed_seconds = int(time_info.get('TS', 0))
        except (ValueError, TypeError):
            passed_minutes = 0
            passed_seconds = 0
        
        # Determine match status based on sport and time
        sport = match_data.get('sport', '')
        
        if sport == 'tennis':
            # Tennis doesn't have halftime, check for end of first set
            scores = match_data.get('ss', {})
            
            # Handle different score formats from API
            if isinstance(scores, dict):
                try:
                    # For tennis, check if first set is completed
                    # This could be in different formats: sets won or current set score
                    sets_home = int(scores.get('home', 0)) if scores.get('home') is not None else 0
                    sets_away = int(scores.get('away', 0)) if scores.get('away') is not None else 0
                except (ValueError, TypeError):
                    sets_home = 0
                    sets_away = 0
                
                # First set completed if either player has won a set
                if sets_home + sets_away >= 1:
                    return {
                        'status': 'first_set_complete',
                        'is_halftime': True,  # Treat first set completion as "halftime" for tennis
                        'is_playing': is_playing
                    }
            elif isinstance(scores, str):
                # Sometimes scores come as strings, try to parse them
                try:
                    # Handle formats like "1-0", "2:1", etc. (sets won)
                    if '-' in scores:
                        home_str, away_str = scores.split('-', 1)
                    elif ':' in scores:
                        home_str, away_str = scores.split(':', 1)
                    else:
                        home_str = away_str = "0"
                    
                    sets_home = int(home_str.strip())
                    sets_away = int(away_str.strip())
                    
                    # First set completed if either player has won a set
                    if sets_home + sets_away >= 1:
                        return {
                            'status': 'first_set_complete',
                            'is_halftime': True,
                            'is_playing': is_playing
                        }
                except (ValueError, AttributeError):
                    # If we can't parse, treat as no score available
                    pass
        
        elif sport == 'basketball':
            # Basketball: 4 quarters of 12 minutes each (48 minutes total)
            # Halftime is after 2nd quarter (24 minutes)
            if 22 <= passed_minutes <= 26:  # Halftime window (around 24 minutes)
                return {
                    'status': 'halftime',
                    'is_halftime': True,
                    'is_playing': is_playing
                }
            elif passed_minutes > 26 and passed_minutes < 46:  # Third quarter
                return {
                    'status': 'third_quarter',
                    'is_halftime': False,
                    'is_playing': is_playing
                }
            elif passed_minutes >= 46:  # Fourth quarter or overtime
                return {
                    'status': 'fourth_quarter',
                    'is_halftime': False,
                    'is_playing': is_playing
                }
            else:  # First or second quarter
                return {
                    'status': 'first_half',
                    'is_halftime': False,
                    'is_playing': is_playing
                }
        
        elif sport == 'handball':
            # Handball: 2 halves of 30 minutes each (60 minutes total)
            # Halftime is around 30 minutes
            if 28 <= passed_minutes <= 32:  # Halftime window (around 30 minutes)
                return {
                    'status': 'halftime',
                    'is_halftime': True,
                    'is_playing': is_playing
                }
            elif passed_minutes > 32:  # Second half
                return {
                    'status': 'second_half',
                    'is_halftime': False,
                    'is_playing': is_playing
                }
            else:  # First half
                return {
                    'status': 'first_half',
                    'is_halftime': False,
                    'is_playing': is_playing
                }
        
        # Default fallback
        return {
            'status': 'first_half',
            'is_halftime': False,
            'is_playing': is_playing
        }
    
    def extract_odds_from_api_response(self, odds_data, sport: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Extract home, away, and draw odds from various API response formats
        
        Args:
            odds_data: The odds data from API (can be list, dict, or other formats)
            sport: Sport name for sport-specific logic
            
        Returns:
            Tuple of (home_odds, away_odds, draw_odds) where draw_odds is None for tennis
        """
        home_odds = None
        away_odds = None
        draw_odds = None
        
        try:
            # Handle different odds structures
            if isinstance(odds_data, list) and len(odds_data) >= 2:
                # Simple list format [home, away, draw]
                if isinstance(odds_data[0], dict) and 'odds' in odds_data[0]:
                    home_odds = float(odds_data[0]['odds'])
                if isinstance(odds_data[1], dict) and 'odds' in odds_data[1]:
                    away_odds = float(odds_data[1]['odds'])
                if len(odds_data) > 2 and isinstance(odds_data[2], dict) and 'odds' in odds_data[2] and sport != 'tennis':
                    draw_odds = float(odds_data[2]['odds'])
                    
            elif isinstance(odds_data, dict):
                # Complex nested structure - try multiple parsing strategies
                logger.debug(f"Parsing odds structure for {sport}: {type(odds_data)}")
                
                # Strategy 1: Tennis structure (main.sp.to_win_match.odds)
                if sport == 'tennis':
                    main_data = odds_data.get('main', {})
                    if isinstance(main_data, dict):
                        sp_data = main_data.get('sp', {})
                        if isinstance(sp_data, dict):
                            to_win_match = sp_data.get('to_win_match', {})
                            if isinstance(to_win_match, dict):
                                odds_list = to_win_match.get('odds', [])
                                if isinstance(odds_list, list) and len(odds_list) >= 2:
                                    if isinstance(odds_list[0], dict) and 'odds' in odds_list[0]:
                                        home_odds = float(odds_list[0]['odds'])
                                    if isinstance(odds_list[1], dict) and 'odds' in odds_list[1]:
                                        away_odds = float(odds_list[1]['odds'])
                
                # Strategy 2: Basketball/Handball structures
                elif sport in ['basketball', 'handball']:
                    # Try multiple common structures for these sports
                    paths_to_try = [
                        ['main', 'sp', 'full_time_result'],
                        ['main', 'sp', 'game_lines'],
                        ['main', 'sp', 'match_result'],
                        ['main', 'sp', 'winner'],
                        ['main', 'sp', 'money_line'],
                        ['sp', 'full_time_result'],
                        ['sp', 'game_lines'],
                        ['sp', 'match_result'],
                        ['sp', 'winner'],
                        ['sp', 'money_line']
                    ]
                    
                    for path in paths_to_try:
                        current_data = odds_data
                        
                        # Navigate through the path
                        for key in path:
                            if isinstance(current_data, dict) and key in current_data:
                                current_data = current_data[key]
                            else:
                                current_data = None
                                break
                        
                        if current_data and isinstance(current_data, dict):
                            odds_list = current_data.get('odds', [])
                            if isinstance(odds_list, list) and len(odds_list) >= 2:
                                # Try to find home/away odds by position or by header
                                for i, odds_item in enumerate(odds_list):
                                    if isinstance(odds_item, dict):
                                        odds_value = odds_item.get('odds')
                                        header = odds_item.get('header', '')
                                        name = odds_item.get('name', '')
                                        
                                        # Identify odds by header or position
                                        if header == '1' or name.lower() in ['home', '1', 'home team'] or i == 0:
                                            if odds_value is not None:
                                                home_odds = float(odds_value)
                                        elif header == '2' or name.lower() in ['away', '2', 'away team'] or i == 1:
                                            if odds_value is not None:
                                                away_odds = float(odds_value)
                                        elif header == 'X' or header == '0' or name.lower() in ['draw', 'tie', 'x'] or i == 2:
                                            if odds_value is not None and sport != 'tennis':
                                                draw_odds = float(odds_value)
                                
                                # If we found odds, break out of the path loop
                                if home_odds is not None and away_odds is not None:
                                    logger.debug(f"Successfully extracted {sport} odds using path: {path}")
                                    break
                
                # Strategy 3: Fallback - recursive search for any odds structure
                if home_odds is None or away_odds is None:
                    logger.debug(f"Falling back to recursive search for {sport} odds")
                    
                    def find_odds_recursive(data, depth=0, path=""):
                        """Recursively search for odds in nested structure"""
                        if depth > 4:  # Prevent infinite recursion
                            return []
                        
                        found_odds = []
                        if isinstance(data, dict):
                            # Look for 'odds' key with list value
                            if 'odds' in data:
                                odds_val = data['odds']
                                if isinstance(odds_val, list):
                                    for item in odds_val:
                                        if isinstance(item, dict) and 'odds' in item:
                                            try:
                                                found_odds.append(float(item['odds']))
                                            except (ValueError, TypeError):
                                                pass
                                elif isinstance(odds_val, (int, float, str)):
                                    try:
                                        found_odds.append(float(odds_val))
                                    except (ValueError, TypeError):
                                        pass
                            
                            # Recursively search nested dictionaries
                            for key, value in data.items():
                                if key != 'odds':  # Avoid infinite loops
                                    found_odds.extend(find_odds_recursive(value, depth + 1, f"{path}.{key}"))
                        
                        return found_odds
                    
                    found_odds = find_odds_recursive(odds_data)
                    if len(found_odds) >= 2:
                        home_odds = found_odds[0] if home_odds is None else home_odds
                        away_odds = found_odds[1] if away_odds is None else away_odds
                        if len(found_odds) > 2 and sport != 'tennis':
                            draw_odds = found_odds[2] if draw_odds is None else draw_odds
                        logger.debug(f"Recursive search found {len(found_odds)} odds for {sport}")
                            
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Error parsing odds structure for {sport}: {str(e)}")
            return None, None, None
        
        # Log success/failure
        if home_odds is not None and away_odds is not None:
            logger.debug(f"Successfully extracted odds for {sport}: home={home_odds}, away={away_odds}, draw={draw_odds}")
        else:
            logger.warning(f"Failed to extract complete odds for {sport}: home={home_odds}, away={away_odds}")
        
        return home_odds, away_odds, draw_odds

    def is_favorite_trailing(self, match: Match, current_score) -> bool:
        """Check if the favorite is trailing"""
        try:
            # Handle different score formats (dict or string)
            if isinstance(current_score, dict):
                home_score = current_score.get('home', 0)
                away_score = current_score.get('away', 0)
            elif isinstance(current_score, str):
                # Parse string scores using the parse_scores method
                home_score, away_score = self.parse_scores(current_score)
            else:
                # Fallback for any other type
                logger.warning(f"Unexpected score format for match {match.event_id}: {type(current_score)}")
                return False
            
            # Safe int conversion
            try:
                home_score = int(home_score) if home_score is not None else 0
                away_score = int(away_score) if away_score is not None else 0
            except (ValueError, TypeError):
                logger.warning(f"Invalid score data for match {match.event_id}: home={home_score}, away={away_score}")
                return False
            
            if match.pre_match_favorite == 'home':
                return home_score < away_score
            else:
                return away_score < home_score
                
        except Exception as e:
            logger.error(f"Error checking if favorite is trailing for match {match.event_id}: {str(e)}")
            return False
    
    async def fetch_and_update_matches(self):
        """Fetch live matches and update database"""
        db = SessionLocal()
        try:
            for sport in self.monitored_sports:
                logger.debug(f"🔍 Fetching {sport} matches...")
                
                # Get upcoming matches for pre-match odds
                try:
                    upcoming_matches = self.api.get_featured_games(sport, limit=20)
                    if not isinstance(upcoming_matches, list):
                        logger.warning(f"⚠️ API returned unexpected data type for {sport} upcoming matches: {type(upcoming_matches)}")
                        if isinstance(upcoming_matches, dict) and 'error' in upcoming_matches:
                            logger.error(f"❌ API error for {sport} upcoming: {upcoming_matches['error']}")
                        upcoming_matches = []
                    else:
                        logger.debug(f"📊 Found {len(upcoming_matches)} upcoming {sport} matches")
                except Exception as api_error:
                    logger.error(f"❌ API error fetching upcoming {sport} matches: {str(api_error)}")
                    upcoming_matches = []
                
                matches_processed = 0
                matches_added = 0
                
                for match_data in upcoming_matches:
                    event_id = match_data.get('id')
                    if not event_id:
                        continue
                    
                    matches_processed += 1
                    
                    # Check if match already exists
                    existing_match = db.query(Match).filter_by(event_id=str(event_id)).first()
                    
                    if not existing_match:
                        # Get pre-match odds with safe float conversion
                        odds = match_data.get('odds', {})
                        if not odds:
                            logger.debug(f"⚠️ No odds data found for {sport} match {event_id}")
                            continue
                        
                        try:
                            # Safe float conversion with None checking
                            home_odds_raw, away_odds_raw, draw_odds_raw = self.extract_odds_from_api_response(odds, sport)
                            
                            if home_odds_raw is None and away_odds_raw is None:
                                logger.warning(f"⚠️ Could not extract odds from data for {sport} match {event_id}")
                                logger.debug(f"Odds structure was: {type(odds)}")
                                continue
                            
                            home_odds = float(home_odds_raw) if home_odds_raw is not None else 999.0
                            away_odds = float(away_odds_raw) if away_odds_raw is not None else 999.0
                            draw_odds = float(draw_odds_raw) if draw_odds_raw is not None and sport != 'tennis' else None
                            
                            # Skip if essential odds are missing
                            if home_odds == 999.0 or away_odds == 999.0:
                                logger.warning(f"⚠️ Skipping {sport} match {event_id} - missing essential odds")
                                continue
                            
                            # Determine favorite
                            favorite = self.get_pre_match_favorite(home_odds, away_odds)
                            
                            # Safe datetime parsing
                            start_time_str = match_data.get('time')
                            if start_time_str:
                                try:
                                    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                                except (ValueError, AttributeError):
                                    start_time = datetime.now(UTC)
                            else:
                                start_time = datetime.now(UTC)
                            
                            # Check if match already exists to avoid duplicates
                            existing_match = db.query(Match).filter_by(event_id=str(event_id)).first()
                            if existing_match:
                                # Update existing match with latest pre-match odds
                                existing_match.pre_match_home_odds = home_odds
                                existing_match.pre_match_away_odds = away_odds
                                existing_match.pre_match_draw_odds = draw_odds
                                existing_match.pre_match_favorite = favorite
                                existing_match.start_time = start_time
                                existing_match.updated_at = datetime.now(UTC)
                                # Commit update immediately
                                try:
                                    db.commit()
                                    logger.debug(f"✅ Updated existing {sport} match: {existing_match.home_team} vs {existing_match.away_team}")
                                except Exception as update_error:
                                    logger.warning(f"⚠️ Error committing {sport} match update {event_id}: {str(update_error)}")
                                    db.rollback()
                            else:
                                # Create new match record
                                home_team = match_data.get('home', {}).get('name', 'Unknown Home')
                                away_team = match_data.get('away', {}).get('name', 'Unknown Away')
                                league_name = match_data.get('league', {}).get('name', 'Unknown League')
                                
                                new_match = Match(
                                    event_id=str(event_id),
                                    sport=sport,
                                    home_team=home_team,
                                    away_team=away_team,
                                    league_name=league_name,
                                    start_time=start_time,
                                    pre_match_home_odds=home_odds,
                                    pre_match_away_odds=away_odds,
                                    pre_match_draw_odds=draw_odds,
                                    pre_match_favorite=favorite,
                                    status='scheduled'
                                )
                                db.add(new_match)
                                # Commit immediately to avoid batching issues with duplicates
                                try:
                                    db.commit()
                                    matches_added += 1
                                    logger.info(f"➕ Added new {sport} match: {home_team} vs {away_team} (odds: {home_odds:.2f}/{away_odds:.2f})")
                                except Exception as commit_error:
                                    logger.warning(f"⚠️ Error committing new {sport} match {event_id}: {str(commit_error)}")
                                    db.rollback()
                                    continue
                            
                        except (ValueError, TypeError) as e:
                            logger.error(f"❌ Error processing odds for {sport} match {event_id}: {str(e)}")
                            continue
                
                if matches_processed > 0:
                    logger.debug(f"📊 {sport}: processed {matches_processed} upcoming matches, added {matches_added} new ones")
                
                # Get in-play matches
                try:
                    inplay_matches = self.api.get_inplay_events(sport, limit='all')
                    if not isinstance(inplay_matches, list):
                        logger.warning(f"API returned unexpected data type for {sport} inplay matches: {type(inplay_matches)}")
                        if isinstance(inplay_matches, dict) and 'error' in inplay_matches:
                            logger.error(f"API error for {sport} inplay: {inplay_matches['error']}")
                        inplay_matches = []
                except Exception as api_error:
                    logger.error(f"API error fetching inplay {sport} matches: {str(api_error)}")
                    inplay_matches = []
                
                if isinstance(inplay_matches, list) and inplay_matches:
                    for match_data in inplay_matches:
                        event_id = match_data.get('id')
                        if not event_id:
                            continue
                        
                        # Find existing match or create new one
                        match = db.query(Match).filter_by(event_id=str(event_id)).first()
                        
                        if match:
                            try:
                                # Validate match data structure
                                if not isinstance(match_data, dict):
                                    logger.warning(f"Invalid match data structure for existing match {event_id}")
                                    continue
                                
                                # Update match status and scores
                                match_data['sport'] = sport  # Add sport info for parsing
                                time_info = self.parse_match_time(match_data)
                                
                                # Update scores with safe int conversion
                                scores = match_data.get('ss', {})
                                if not isinstance(scores, (dict, str)):
                                    logger.warning(f"Invalid scores structure for match {event_id}: {type(scores)}")
                                    scores = {}
                                
                                home_score, away_score = self.parse_scores(scores)
                                match.current_score_home = home_score
                                match.current_score_away = away_score
                                
                                # Update status
                                if time_info['is_halftime']:
                                    match.status = 'halftime'
                                    
                                    # Check if favorite is trailing
                                    if self.is_favorite_trailing(match, scores):
                                        match.favorite_trailing_at_halftime = True
                                        
                                        # Get current live odds with safe conversion
                                        current_odds = match_data.get('odds', {})
                                        if current_odds:
                                            try:
                                                home_live_odds, away_live_odds, draw_live_odds = self.extract_odds_from_api_response(current_odds, sport)
                                                
                                                if home_live_odds is not None:
                                                    match.halftime_home_odds = float(home_live_odds)
                                                if away_live_odds is not None:
                                                    match.halftime_away_odds = float(away_live_odds)
                                                if draw_live_odds is not None and sport != 'tennis':
                                                    match.halftime_draw_odds = float(draw_live_odds)
                                                    
                                            except (ValueError, TypeError) as e:
                                                logger.warning(f"Error processing live odds for match {event_id}: {str(e)}")
                                
                                elif time_info['status'] == 'second_half':
                                    match.status = 'live'
                                else:
                                    match.status = 'live'
                                
                                # Commit the match updates immediately
                                try:
                                    db.commit()
                                    logger.debug(f"Updated existing inplay match: {match.home_team} vs {match.away_team}")
                                except Exception as commit_error:
                                    logger.warning(f"Error committing inplay match update {event_id}: {str(commit_error)}")
                                    db.rollback()
                                    
                            except Exception as e:
                                logger.error(f"Error updating match {event_id}: {str(e)}")
                                logger.debug(f"Match data that caused error: {match_data}")
                                continue
                        
                        else:
                            # Create match with live data if no pre-match data exists
                            self.live_matches_created += 1
                            
                            try:
                                # Validate match data structure first
                                if not isinstance(match_data, dict):
                                    logger.warning(f"Invalid match data structure for {event_id}: expected dict, got {type(match_data)}")
                                    continue
                                
                                # Get current live odds as "pre-match" for notification purposes
                                current_odds = match_data.get('odds', {})
                                
                                if current_odds:
                                    # Use current live odds as baseline
                                    home_odds_raw, away_odds_raw, draw_odds_raw = self.extract_odds_from_api_response(current_odds, sport)
                                    
                                    if home_odds_raw is None or away_odds_raw is None:
                                        logger.warning(f"Missing essential odds data for match {event_id}")
                                        continue
                                    
                                    home_odds = float(home_odds_raw) if home_odds_raw is not None else 999.0
                                    away_odds = float(away_odds_raw) if away_odds_raw is not None else 999.0
                                    draw_odds = float(draw_odds_raw) if draw_odds_raw is not None and sport != 'tennis' else None
                                    
                                    # Skip if essential odds are missing
                                    if home_odds == 999.0 or away_odds == 999.0:
                                        continue  # Skip silently, these are common
                                    
                                    # Determine favorite from current odds
                                    favorite = self.get_pre_match_favorite(home_odds, away_odds)
                                    
                                    # Get match info with validation
                                    home_team_data = match_data.get('home', {})
                                    away_team_data = match_data.get('away', {})
                                    league_data = match_data.get('league', {})
                                    
                                    if not isinstance(home_team_data, dict) or not isinstance(away_team_data, dict):
                                        logger.warning(f"Invalid team data structure for match {event_id}")
                                        continue
                                    
                                    home_team = home_team_data.get('name', 'Unknown Home')
                                    away_team = away_team_data.get('name', 'Unknown Away')
                                    league_name = league_data.get('name', 'Unknown League') if isinstance(league_data, dict) else 'Unknown League'
                                    
                                    # Parse current scores with validation
                                    scores = match_data.get('ss', {})
                                    if not isinstance(scores, (dict, str)):
                                        logger.warning(f"Invalid scores structure for match {event_id}: {type(scores)}")
                                        scores = {}
                                    
                                    home_score, away_score = self.parse_scores(scores)
                                    
                                    # Parse match timing - only if we have valid data structure
                                    match_data['sport'] = sport
                                    time_info = self.parse_match_time(match_data)
                                    
                                    # Determine status
                                    status = 'live'
                                    favorite_trailing = False
                                    
                                    if time_info['is_halftime']:
                                        status = 'halftime'
                                        # Check if favorite is trailing (using live odds as reference)
                                        if favorite == 'home':
                                            favorite_trailing = home_score < away_score
                                        else:
                                            favorite_trailing = away_score < home_score
                                    
                                    # Create new match from live data - but check for duplicates first
                                    # Use merge to handle potential duplicates gracefully
                                    new_match = Match(
                                        event_id=str(event_id),
                                        sport=sport,
                                        home_team=home_team,
                                        away_team=away_team,
                                        league_name=league_name,
                                        start_time=datetime.now(UTC) - timedelta(minutes=30),  # Estimate start time
                                        pre_match_home_odds=home_odds,  # Use current odds as reference
                                        pre_match_away_odds=away_odds,
                                        pre_match_draw_odds=draw_odds,
                                        pre_match_favorite=favorite,
                                        status=status,
                                        current_score_home=home_score,
                                        current_score_away=away_score,
                                        halftime_home_odds=home_odds,
                                        halftime_away_odds=away_odds,
                                        halftime_draw_odds=draw_odds,
                                        favorite_trailing_at_halftime=favorite_trailing,
                                        start_notification_sent=True  # Skip start notification for already-live matches
                                    )
                                    
                                    # Check if match already exists to avoid duplicate key violations
                                    existing_match_check = db.query(Match).filter_by(event_id=str(event_id)).first()
                                    if existing_match_check:
                                        # Update existing match with live data
                                        existing_match_check.status = status
                                        existing_match_check.current_score_home = home_score
                                        existing_match_check.current_score_away = away_score
                                        existing_match_check.favorite_trailing_at_halftime = favorite_trailing
                                        existing_match_check.halftime_home_odds = home_odds
                                        existing_match_check.halftime_away_odds = away_odds
                                        existing_match_check.halftime_draw_odds = draw_odds
                                        existing_match_check.updated_at = datetime.now(UTC)
                                        # Commit update immediately
                                        try:
                                            db.commit()
                                            logger.debug(f"Updated existing match: {home_team} vs {away_team}")
                                        except Exception as update_error:
                                            logger.warning(f"Error committing live match update {event_id}: {str(update_error)}")
                                            db.rollback()
                                    else:
                                        # Safe to add new match
                                        db.add(new_match)
                                        # Commit immediately to avoid batching issues with duplicates
                                        try:
                                            db.commit()
                                            self.live_matches_created += 1
                                            logger.debug(f"Added new live match: {home_team} vs {away_team}")
                                        except Exception as commit_error:
                                            logger.warning(f"Error committing new live match {event_id}: {str(commit_error)}")
                                            db.rollback()
                                    
                                else:
                                    continue  # Skip silently if no odds data
                                    
                            except Exception as e:
                                logger.error(f"Error creating live match {event_id}: {str(e)}")
                                logger.debug(f"Match data that caused error: {match_data}")
                                continue
                
                # Final commit for any remaining operations
                try:
                    db.commit()
                except Exception as final_commit_error:
                    logger.warning(f"Final commit had minor issues: {str(final_commit_error)}")
                    db.rollback()
                
                # Show periodic summary instead of individual match logs
                if datetime.now(UTC) - self.last_summary_time > timedelta(minutes=5):
                    total_matches = db.query(Match).count()
                    live_matches = db.query(Match).filter(Match.status.in_(['live', 'halftime'])).count()
                    
                    logger.info(f"📊 Tracking Summary: {total_matches} total matches, {live_matches} currently live, {self.live_matches_created} created from live data")
                    self.live_matches_created = 0  # Reset counter
                    self.last_summary_time = datetime.now(UTC)
                
        except Exception as e:
            logger.error(f"Error updating matches: {str(e)}")
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"Exception details: {repr(e)}")
            if hasattr(e, '__traceback__'):
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
            db.rollback()
        finally:
            db.close()
    
    async def get_matches_for_notification(self) -> Dict[str, List[Match]]:
        """Get matches that need notifications (only for paid subscribers)"""
        db = SessionLocal()
        try:
            notifications_needed = {
                'match_start': [],
                'halftime_trailing': []
            }
            
            # Get matches starting soon - notify 30 minutes before (25-35 minute window)
            now = datetime.now(UTC)
            notification_window_start = now + timedelta(minutes=25)  # Start notifying 35 minutes before
            notification_window_end = now + timedelta(minutes=35)    # Stop notifying 25 minutes before
            
            # Only get matches that start within the notification window
            starting_matches = db.query(Match).filter(
                Match.status == 'scheduled',
                Match.start_time >= notification_window_start,
                Match.start_time <= notification_window_end,
                Match.start_notification_sent == False
            ).all()
            
            # Filter matches that have active paid subscribers for the sport
            filtered_starting_matches = []
            for match in starting_matches:
                # Check if there are any active paid subscribers for this sport
                from database import User, Subscription
                from sqlalchemy import and_, or_, text
                active_subscribers = db.query(User).join(Subscription).filter(
                    and_(
                        Subscription.is_active == True,
                        Subscription.end_date > datetime.now(UTC),
                        or_(
                            # Full access plan includes all sports
                            Subscription.plan_type == 'full_access',
                            # Use PostgreSQL JSON contains operator
                            text(f"subscriptions.sports::jsonb ? '{match.sport}'")
                        )
                    )
                ).count()
                
                if active_subscribers > 0:
                    # Calculate time until match starts
                    time_to_start = match.start_time - datetime.now(UTC)
                    minutes_to_start = int(time_to_start.total_seconds() / 60)
                    
                    # Include matches that start in 25-35 minutes
                    if 25 <= minutes_to_start <= 35:
                        filtered_starting_matches.append(match)
                        logger.info(f"Match {match.home_team} vs {match.away_team} starts in {minutes_to_start} minutes - queuing pre-match notification")
            
            notifications_needed['match_start'] = filtered_starting_matches
            
            # Get matches where favorite is trailing at halftime (also only for paid subscribers)
            halftime_matches = db.query(Match).filter(
                Match.status == 'halftime',
                Match.favorite_trailing_at_halftime == True,
                Match.halftime_notification_sent == False
            ).all()
            
            # Filter halftime matches for paid subscribers
            filtered_halftime_matches = []
            for match in halftime_matches:
                from database import User, Subscription
                from sqlalchemy import and_, or_, text
                active_subscribers = db.query(User).join(Subscription).filter(
                    and_(
                        Subscription.is_active == True,
                        Subscription.end_date > datetime.now(UTC),
                        or_(
                            # Full access plan includes all sports
                            Subscription.plan_type == 'full_access',
                            # Use PostgreSQL JSON contains operator
                            text(f"subscriptions.sports::jsonb ? '{match.sport}'")
                        )
                    )
                ).count()
                
                if active_subscribers > 0:
                    filtered_halftime_matches.append(match)
            
            notifications_needed['halftime_trailing'] = filtered_halftime_matches
            
            return notifications_needed
            
        finally:
            db.close()
    
    async def mark_notification_sent(self, match_id: int, notification_type: str):
        """Mark that a notification has been sent for a match"""
        db = SessionLocal()
        try:
            match = db.query(Match).filter_by(id=match_id).first()
            if match:
                if notification_type == 'match_start':
                    match.start_notification_sent = True
                elif notification_type == 'halftime_trailing':
                    match.halftime_notification_sent = True
                db.commit()
        finally:
            db.close()
    
    async def run_continuous_tracking(self):
        """Run continuous tracking of matches"""
        logger.info("Starting continuous odds tracking...")
        logger.info("🎯 Monitoring sports: tennis, basketball, handball")
        logger.info("⏰ Pre-match notifications: 30 minutes before match start")
        logger.info("🏃 Live tracking: Every 15 seconds for active matches")
        logger.info("📊 Scheduled matches: Every 60 seconds")
        
        cleanup_counter = 0
        cycle_count = 0
        
        while True:
            try:
                cycle_count += 1
                start_time = datetime.now(UTC)
                
                # Log periodic status
                if cycle_count % 20 == 1:  # Every 20 cycles
                    db = SessionLocal()
                    try:
                        total_matches = db.query(Match).count()
                        live_matches = db.query(Match).filter(Match.status.in_(['live', 'halftime'])).count()
                        scheduled_matches = db.query(Match).filter(Match.status == 'scheduled').count()
                        logger.info(f"📊 Status: {total_matches} total matches | {live_matches} live | {scheduled_matches} scheduled")
                    finally:
                        db.close()
                
                await self.fetch_and_update_matches()
                
                # Run cleanup every 40 cycles (approximately every 10 minutes at 15s intervals)
                cleanup_counter += 1
                if cleanup_counter >= 40:
                    await self.cleanup_old_matches()
                    cleanup_counter = 0
                
                # Dynamic sleep based on live match activity
                db = SessionLocal()
                try:
                    live_match_count = db.query(Match).filter(Match.status.in_(['live', 'halftime'])).count()
                    
                    if live_match_count > 0:
                        # More frequent updates when there are live matches
                        sleep_time = 15  # 15 seconds for live matches
                        if cycle_count % 10 == 1:
                            logger.info(f"🏃 Fast tracking: {live_match_count} live matches - checking every {sleep_time}s")
                    else:
                        # Less frequent when only scheduled matches
                        sleep_time = 60  # 60 seconds for scheduled only
                        if cycle_count % 5 == 1:
                            logger.info(f"⏳ Slow tracking: No live matches - checking every {sleep_time}s")
                finally:
                    db.close()
                
                # Calculate actual processing time and adjust sleep
                processing_time = (datetime.now(UTC) - start_time).total_seconds()
                actual_sleep = max(1, sleep_time - processing_time)  # At least 1 second sleep
                
                await asyncio.sleep(actual_sleep)
                
            except Exception as e:
                logger.error(f"Error in continuous tracking (cycle {cycle_count}): {str(e)}")
                await asyncio.sleep(60)  # Wait longer on error

    async def cleanup_old_matches(self):
        """Clean up old finished matches to prevent database bloat"""
        db = SessionLocal()
        try:
            # Remove matches older than 24 hours that are finished
            cutoff_time = datetime.now(UTC) - timedelta(hours=24)
            
            old_matches = db.query(Match).filter(
                Match.updated_at < cutoff_time,
                Match.status.in_(['finished', 'completed', 'cancelled'])
            ).all()
            
            if old_matches:
                for match in old_matches:
                    db.delete(match)
                
                db.commit()
                logger.info(f"Cleaned up {len(old_matches)} old matches")
                
        except Exception as e:
            logger.error(f"Error cleaning up old matches: {str(e)}")
            db.rollback()
        finally:
            db.close()

# Singleton instance
odds_tracker = OddsTracker() 