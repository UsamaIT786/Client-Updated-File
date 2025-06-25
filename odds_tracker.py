import asyncio
import logging
from datetime import datetime, timedelta
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
        self.last_summary_time = datetime.utcnow()
        
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
                    sets_home = int(scores.get('home', 0)) if scores.get('home') is not None else 0
                    sets_away = int(scores.get('away', 0)) if scores.get('away') is not None else 0
                except (ValueError, TypeError):
                    sets_home = 0
                    sets_away = 0
                
                if sets_home + sets_away >= 1:
                    return {
                        'status': 'first_set_complete',
                        'is_halftime': True,  # Treat first set completion as "halftime" for tennis
                        'is_playing': is_playing
                    }
            elif isinstance(scores, str):
                # Sometimes scores come as strings, try to parse them
                try:
                    # Handle formats like "1-0", "2:1", etc.
                    if '-' in scores:
                        home_str, away_str = scores.split('-', 1)
                    elif ':' in scores:
                        home_str, away_str = scores.split(':', 1)
                    else:
                        home_str = away_str = "0"
                    
                    sets_home = int(home_str.strip())
                    sets_away = int(away_str.strip())
                    
                    if sets_home + sets_away >= 1:
                        return {
                            'status': 'first_set_complete',
                            'is_halftime': True,
                            'is_playing': is_playing
                        }
                except (ValueError, AttributeError):
                    # If we can't parse, treat as no score available
                    pass
        
        elif sport in ['basketball', 'handball']:
            # Basketball and handball have halftime
            # Usually around 20-25 minutes for handball, 24 minutes for basketball (2 quarters)
            halftime_minutes = 25 if sport == 'handball' else 24
            
            if passed_minutes >= halftime_minutes and passed_minutes <= halftime_minutes + 5:
                return {
                    'status': 'halftime',
                    'is_halftime': True,
                    'is_playing': is_playing
                }
            elif passed_minutes > halftime_minutes + 5:
                return {
                    'status': 'second_half',
                    'is_halftime': False,
                    'is_playing': is_playing
                }
        
        return {
            'status': 'first_half',
            'is_halftime': False,
            'is_playing': is_playing
        }
    
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
                logger.info(f"Fetching {sport} matches...")
                
                # Get upcoming matches for pre-match odds
                upcoming_matches = self.api.get_featured_games(sport, limit=20)
                
                for match_data in upcoming_matches:
                    event_id = match_data.get('id')
                    if not event_id:
                        continue
                    
                    # Check if match already exists
                    existing_match = db.query(Match).filter_by(event_id=str(event_id)).first()
                    
                    if not existing_match:
                        # Get pre-match odds with safe float conversion
                        odds = match_data.get('odds', [])
                        if not odds or len(odds) < 2:
                            continue
                        
                        try:
                            # Safe float conversion with None checking
                            home_odds_raw = odds[0].get('odds') if len(odds) > 0 else None
                            away_odds_raw = odds[1].get('odds') if len(odds) > 1 else None
                            draw_odds_raw = odds[2].get('odds') if len(odds) > 2 else None
                            
                            home_odds = float(home_odds_raw) if home_odds_raw is not None else 999.0
                            away_odds = float(away_odds_raw) if away_odds_raw is not None else 999.0
                            draw_odds = float(draw_odds_raw) if draw_odds_raw is not None and sport != 'tennis' else None
                            
                            # Skip if essential odds are missing
                            if home_odds == 999.0 or away_odds == 999.0:
                                logger.warning(f"Skipping match {event_id} - missing essential odds")
                                continue
                            
                            # Determine favorite
                            favorite = self.get_pre_match_favorite(home_odds, away_odds)
                            
                            # Safe datetime parsing
                            start_time_str = match_data.get('time')
                            if start_time_str:
                                try:
                                    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                                except (ValueError, AttributeError):
                                    start_time = datetime.utcnow()
                            else:
                                start_time = datetime.utcnow()
                            
                            # Create new match record
                            new_match = Match(
                                event_id=str(event_id),
                                sport=sport,
                                home_team=match_data.get('home', {}).get('name', 'Unknown Home'),
                                away_team=match_data.get('away', {}).get('name', 'Unknown Away'),
                                league_name=match_data.get('league', {}).get('name', 'Unknown League'),
                                start_time=start_time,
                                pre_match_home_odds=home_odds,
                                pre_match_away_odds=away_odds,
                                pre_match_draw_odds=draw_odds,
                                pre_match_favorite=favorite,
                                status='scheduled'
                            )
                            db.add(new_match)
                            logger.info(f"Added new match: {new_match.home_team} vs {new_match.away_team}")
                            
                        except (ValueError, TypeError) as e:
                            logger.error(f"Error processing odds for match {event_id}: {str(e)}")
                            continue
                
                # Get in-play matches
                inplay_matches = self.api.get_inplay_events(sport, limit='all')
                
                if isinstance(inplay_matches, list):
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
                                        current_odds = match_data.get('odds', [])
                                        if isinstance(current_odds, list) and len(current_odds) >= 2:
                                            try:
                                                home_live_odds = current_odds[0].get('odds') if isinstance(current_odds[0], dict) else None
                                                away_live_odds = current_odds[1].get('odds') if isinstance(current_odds[1], dict) else None
                                                draw_live_odds = current_odds[2].get('odds') if len(current_odds) > 2 and isinstance(current_odds[2], dict) else None
                                                
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
                                current_odds = match_data.get('odds', [])
                                
                                # Ensure current_odds is a list
                                if not isinstance(current_odds, list):
                                    logger.warning(f"Invalid odds structure for match {event_id}: expected list, got {type(current_odds)}")
                                    continue
                                
                                if current_odds and len(current_odds) >= 2:
                                    # Use current live odds as baseline
                                    home_odds_raw = current_odds[0].get('odds') if isinstance(current_odds[0], dict) else None
                                    away_odds_raw = current_odds[1].get('odds') if isinstance(current_odds[1], dict) else None
                                    draw_odds_raw = current_odds[2].get('odds') if len(current_odds) > 2 and isinstance(current_odds[2], dict) else None
                                    
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
                                    
                                    # Create new match from live data
                                    new_match = Match(
                                        event_id=str(event_id),
                                        sport=sport,
                                        home_team=home_team,
                                        away_team=away_team,
                                        league_name=league_name,
                                        start_time=datetime.utcnow() - timedelta(minutes=30),  # Estimate start time
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
                                    
                                    db.add(new_match)
                                    
                                else:
                                    continue  # Skip silently if no odds data
                                    
                            except Exception as e:
                                logger.error(f"Error creating live match {event_id}: {str(e)}")
                                logger.debug(f"Match data that caused error: {match_data}")
                                continue
                
                db.commit()
                
                # Show periodic summary instead of individual match logs
                if datetime.utcnow() - self.last_summary_time > timedelta(minutes=5):
                    total_matches = db.query(Match).count()
                    live_matches = db.query(Match).filter(Match.status.in_(['live', 'halftime'])).count()
                    
                    logger.info(f"📊 Tracking Summary: {total_matches} total matches, {live_matches} currently live, {self.live_matches_created} created from live data")
                    self.live_matches_created = 0  # Reset counter
                    self.last_summary_time = datetime.utcnow()
                
        except Exception as e:
            logger.error(f"Error updating matches: {str(e)}")
            db.rollback()
        finally:
            db.close()
    
    async def get_matches_for_notification(self) -> Dict[str, List[Match]]:
        """Get matches that need notifications"""
        db = SessionLocal()
        try:
            notifications_needed = {
                'match_start': [],
                'halftime_trailing': []
            }
            
            # Get matches starting soon (within 5 minutes)
            upcoming_threshold = datetime.utcnow() + timedelta(minutes=5)
            starting_matches = db.query(Match).filter(
                Match.status == 'scheduled',
                Match.start_time <= upcoming_threshold,
                Match.start_notification_sent == False
            ).all()
            
            notifications_needed['match_start'] = starting_matches
            
            # Get matches where favorite is trailing at halftime
            halftime_matches = db.query(Match).filter(
                Match.status == 'halftime',
                Match.favorite_trailing_at_halftime == True,
                Match.halftime_notification_sent == False
            ).all()
            
            notifications_needed['halftime_trailing'] = halftime_matches
            
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
        
        cleanup_counter = 0
        
        while True:
            try:
                await self.fetch_and_update_matches()
                
                # Run cleanup every 20 cycles (approximately every 10 minutes)
                cleanup_counter += 1
                if cleanup_counter >= 20:
                    await self.cleanup_old_matches()
                    cleanup_counter = 0
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in continuous tracking: {str(e)}")
                await asyncio.sleep(60)  # Wait a bit longer on error

    async def cleanup_old_matches(self):
        """Clean up old finished matches to prevent database bloat"""
        db = SessionLocal()
        try:
            # Remove matches older than 24 hours that are finished
            cutoff_time = datetime.utcnow() - timedelta(hours=24)
            
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