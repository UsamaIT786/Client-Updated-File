import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from database import User, Subscription, Payment, NotificationLog, Match, init_db, SessionLocal
from paypal_integration import paypal_service
from odds_tracker import odds_tracker
import env_config

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class BettingBot:
    def __init__(self):
        self.app = None
        self.premium_channel_id = env_config.PREMIUM_CHANNEL_ID
        self.free_channel_id = env_config.FREE_CHANNEL_ID
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        
        # Validate that we have a proper message update
        if not update.message:
            logger.warning("Received start command without message object")
            return
        
        db = SessionLocal()
        
        try:
            # Check if user exists in database
            db_user = db.query(User).filter_by(telegram_id=str(user.id)).first()
            
            if not db_user:
                # Create new user
                db_user = User(
                    telegram_id=str(user.id),
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name
                )
                db.add(db_user)
                db.commit()
            
            # Create welcome message with subscription options
            keyboard = [
                [InlineKeyboardButton("📋 View Plans", callback_data="view_plans")],
                [InlineKeyboardButton("🏆 My Subscriptions", callback_data="my_subscriptions")],
                [InlineKeyboardButton("ℹ️ About", callback_data="about")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            welcome_text = (
                f"Welcome {user.first_name} to Premium Betting Analytics! 🎯\n\n"
                "Get instant notifications when favorites are trailing at halftime:\n"
                "• 🎾 Tennis - When favorite loses first set\n"
                "• 🏀 Basketball - When favorite trails at halftime\n"
                "• 🤾 Handball - When favorite trails at halftime\n\n"
                "Choose your subscription plan below:"
            )
            
            await update.message.reply_text(welcome_text, reply_markup=reply_markup)
            
        finally:
            db.close()
    
    async def view_plans(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display available subscription plans"""
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🏆 1 Sport (Basketball/Handball/Tennis)", callback_data="plan_single_sport")],
            [InlineKeyboardButton("🔥 2 Combined Sports", callback_data="plan_two_sports")],
            [InlineKeyboardButton("👑 Full Access (All 3 Sports)", callback_data="plan_full_access")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        plans_text = (
            "📋 **Available Subscription Plans**\n\n"
            "**🏆 1 Sport (Basketball/Handball/Tennis)**\n"
            f"• 1 Month: €{env_config.PRICING['single_sport'][1]}\n"
            f"• 3 Months: €{env_config.PRICING['single_sport'][3]}\n"
            f"• 6 Months: €{env_config.PRICING['single_sport'][6]}\n\n"
            "**🔥 2 Combined Sports**\n"
            f"• 1 Month: €{env_config.PRICING['two_sports'][1]}\n"
            f"• 3 Months: €{env_config.PRICING['two_sports'][3]}\n"
            f"• 6 Months: €{env_config.PRICING['two_sports'][6]}\n\n"
            "**👑 Full Access (All 3 Sports)**\n"
            f"• 1 Month: €{env_config.PRICING['full_access'][1]}\n"
            f"• 3 Months: €{env_config.PRICING['full_access'][3]}\n"
            f"• 6 Months: €{env_config.PRICING['full_access'][6]}\n\n"
            "Select a plan to continue:"
        )
        
        await query.edit_message_text(
            text=plans_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def show_duration_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show duration selection for chosen plan type"""
        query = update.callback_query
        await query.answer()
        
        plan_type = query.data.replace("plan_", "")
        context.user_data['selected_plan_type'] = plan_type
        
        # Get plan info
        plan_names = {
            'single_sport': '🏆 1 Sport',
            'two_sports': '🔥 2 Combined Sports', 
            'full_access': '👑 Full Access (All 3 Sports)'
        }
        
        plan_name = plan_names.get(plan_type, 'Unknown Plan')
        pricing = env_config.PRICING[plan_type]
        
        keyboard = [
            [InlineKeyboardButton(f"1 Month - €{pricing[1]}", callback_data=f"duration_{plan_type}_1")],
            [InlineKeyboardButton(f"3 Months - €{pricing[3]}", callback_data=f"duration_{plan_type}_3")],
            [InlineKeyboardButton(f"6 Months - €{pricing[6]}", callback_data=f"duration_{plan_type}_6")],
            [InlineKeyboardButton("🔙 Back to Plans", callback_data="view_plans")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            f"**{plan_name}**\n\n"
            "Select your subscription duration:\n\n"
            f"• **1 Month**: €{pricing[1]}\n"
            f"• **3 Months**: €{pricing[3]} (Save €{(pricing[1] * 3) - pricing[3]:.0f}!)\n"
            f"• **6 Months**: €{pricing[6]} (Save €{(pricing[1] * 6) - pricing[6]:.0f}!)\n"
        )
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def handle_duration_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle duration selection and proceed to sport selection or payment"""
        query = update.callback_query
        await query.answer()
        
        # Parse duration selection: duration_plantype_months
        parts = query.data.split('_')
        
        # Handle different callback data formats
        if len(parts) >= 3 and parts[0] == 'duration':
            plan_type = parts[1]
            
            # Special handling for single_sport which has 4 parts: duration_single_sport_months
            if plan_type == 'single' and len(parts) == 4:
                plan_type = 'single_sport'  # Reconstruct the plan type
                try:
                    duration = int(parts[3])  # Duration is in the 4th position
                except ValueError:
                    logger.error(f"Invalid duration in callback data: {query.data}")
                    await query.edit_message_text("❌ Invalid selection. Please try again.")
                    return
            else:
                # Normal format: duration_plantype_months
                try:
                    duration = int(parts[2])
                except ValueError:
                    logger.error(f"Invalid duration in callback data: {query.data}")
                    await query.edit_message_text("❌ Invalid selection. Please try again.")
                    return
        else:
            logger.error(f"Unexpected callback data format: {query.data}")
            await query.edit_message_text("❌ Invalid selection. Please try again.")
            return
        
        context.user_data['selected_plan_type'] = plan_type
        context.user_data['selected_duration'] = duration
        
        if plan_type == 'single_sport':
            # Let user choose which sport
            await self.show_single_sport_selection(query, context)
        elif plan_type == 'two_sports':
            # Let user choose 2 sports
            context.user_data['selecting_sports'] = []
            await self.show_multi_sport_selection(query, context, required_count=2)
        else:  # full_access
            # Proceed directly to payment with all sports
            await self.process_payment_new(query, context, ['tennis', 'basketball', 'handball'])
    
    async def show_single_sport_selection(self, query, context):
        """Show sport selection for single sport plan"""
        keyboard = [
            [InlineKeyboardButton("🎾 Tennis", callback_data="single_sport_tennis")],
            [InlineKeyboardButton("🏀 Basketball", callback_data="single_sport_basketball")],
            [InlineKeyboardButton("🤾 Handball", callback_data="single_sport_handball")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"plan_{context.user_data['selected_plan_type']}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        duration = context.user_data['selected_duration']
        price = env_config.PRICING['single_sport'][duration]
        
        text = (
            f"**🏆 1 Sport Plan - {duration} Month{'s' if duration > 1 else ''}**\n"
            f"**Price**: €{price}\n\n"
            "Choose your sport:"
        )
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def handle_single_sport_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle single sport selection"""
        query = update.callback_query
        await query.answer()
        
        sport = query.data.replace("single_sport_", "")
        await self.process_payment_new(query, context, [sport])
    
    async def show_multi_sport_selection(self, query, context, required_count):
        """Show sport selection for multi-sport plans"""
        selected = context.user_data.get('selecting_sports', [])
        plan_type = context.user_data['selected_plan_type']
        duration = context.user_data['selected_duration']
        
        keyboard = []
        
        # Add sport selection buttons
        sports = [
            ('tennis', '🎾 Tennis'),
            ('basketball', '🏀 Basketball'), 
            ('handball', '🤾 Handball')
        ]
        
        for sport_key, sport_name in sports:
            if sport_key in selected:
                button_text = f"✅ {sport_name}"
            else:
                button_text = sport_name
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"toggle_sport_{sport_key}")])
        
        # Add continue button if correct number selected
        if len(selected) == required_count:
            keyboard.append([InlineKeyboardButton("✅ Continue to Payment", callback_data="confirm_sport_selection")])
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"plan_{plan_type}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        price = env_config.PRICING[plan_type][duration]
        plan_name = "🔥 2 Combined Sports" if plan_type == 'two_sports' else "Plan"
        
        text = (
            f"**{plan_name} - {duration} Month{'s' if duration > 1 else ''}**\n"
            f"**Price**: €{price}\n\n"
            f"Select {required_count} sports ({len(selected)}/{required_count} selected):"
        )
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def handle_sport_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle sport toggle for multi-sport plans"""
        query = update.callback_query
        await query.answer()
        
        sport = query.data.replace("toggle_sport_", "")
        selected = context.user_data.get('selecting_sports', [])
        plan_type = context.user_data['selected_plan_type']
        
        required_count = 2 if plan_type == 'two_sports' else 3
        
        if sport in selected:
            selected.remove(sport)
        else:
            if len(selected) < required_count:
                selected.append(sport)
            else:
                await query.answer(f"You can only select {required_count} sports for this plan", show_alert=True)
                return
        
        context.user_data['selecting_sports'] = selected
        await self.show_multi_sport_selection(query, context, required_count)
    
    async def confirm_sport_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm sport selection and proceed to payment"""
        query = update.callback_query
        await query.answer()
        
        selected_sports = context.user_data.get('selecting_sports', [])
        await self.process_payment_new(query, context, selected_sports)
    
    async def process_payment_new(self, query, context, sports: List[str]):
        """Process payment with new pricing structure"""
        user_id = str(query.from_user.id)
        plan_type = context.user_data['selected_plan_type']
        duration = context.user_data['selected_duration']
        
        # Get price
        price = env_config.PRICING[plan_type][duration]
        
        # Create payment description
        sport_names = {'tennis': 'Tennis', 'basketball': 'Basketball', 'handball': 'Handball'}
        sports_text = ", ".join([sport_names[sport] for sport in sports])
        
        plan_names = {
            'single_sport': '1 Sport',
            'two_sports': '2 Combined Sports',
            'full_access': 'Full Access (All 3 Sports)'
        }
        
        description = f"{plan_names[plan_type]} - {sports_text} - {duration} Month{'s' if duration > 1 else ''}"
        
        # Create PayPal payment
        payment_result = paypal_service.create_payment_new(user_id, plan_type, sports, duration, price, description)
        
        if payment_result:
            # Save payment record
            db = SessionLocal()
            try:
                payment = Payment(
                    user_id=db.query(User).filter_by(telegram_id=user_id).first().id,
                    paypal_payment_id=payment_result['payment_id'],
                    amount=price,
                    status='pending',
                    plan_type=plan_type,
                    sports=sports,
                    duration_months=duration
                )
                db.add(payment)
                db.commit()
                
                # Send payment link
                keyboard = [
                    [InlineKeyboardButton("💳 Pay with PayPal", url=payment_result['approval_url'])],
                    [InlineKeyboardButton("🔙 Back to Plans", callback_data="view_plans")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"📋 **Order Summary**\n\n"
                    f"**Plan**: {description}\n"
                    f"**Amount**: €{price}\n\n"
                    f"Click the button below to complete your payment:",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
            finally:
                db.close()
        else:
            await query.edit_message_text(
                "❌ Error creating payment. Please try again later.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="view_plans")]])
            )
    
    async def my_subscriptions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user's active subscriptions"""
        query = update.callback_query
        await query.answer()
        
        user_id = str(update.effective_user.id)
        db = SessionLocal()
        
        try:
            user = db.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                await query.edit_message_text("User not found. Please /start the bot first.")
                return
            
            active_subs = db.query(Subscription).filter_by(
                user_id=user.id,
                is_active=True
            ).filter(Subscription.end_date > datetime.utcnow()).all()
            
            if not active_subs:
                text = "❌ You don't have any active subscriptions.\n\nTap 'View Plans' to subscribe!"
                keyboard = [[InlineKeyboardButton("📋 View Plans", callback_data="view_plans")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(text, reply_markup=reply_markup)
            else:
                text = "🏆 *Your Active Subscriptions*\n\n"
                for sub in active_subs:
                    # Safely handle sports data
                    if isinstance(sub.sports, list) and sub.sports:
                        sports_text = ", ".join([sport.title() for sport in sub.sports])
                    else:
                        sports_text = "All Sports"
                    
                    # Properly format plan names
                    plan_names = {
                        'single_sport': '1 Sport Plan',
                        'two_sports': '2 Combined Sports Plan', 
                        'full_access': 'Full Access Plan'
                    }
                    plan_display = plan_names.get(sub.plan_type, sub.plan_type.replace('_', ' ').title())
                    
                    # Escape Markdown special characters to prevent parsing errors
                    safe_plan = plan_display.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]')
                    safe_sports = sports_text.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]')
                    
                    text += f"📦 *{safe_plan}*\n"
                    text += f"Sports: {safe_sports}\n"
                    text += f"Expires: {sub.end_date.strftime('%Y-%m-%d')}\n\n"
                
                keyboard = [
                    [InlineKeyboardButton("📋 View Plans", callback_data="view_plans")],
                    [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
                except Exception as markdown_error:
                    logger.error(f"Markdown parsing error in my_subscriptions: {str(markdown_error)}")
                    # Fallback to plain text if Markdown fails
                    fallback_text = text.replace('*', '').replace('_', '').replace('[', '').replace(']', '')
                    await query.edit_message_text(fallback_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in my_subscriptions: {str(e)}")
            # Final fallback message
            try:
                fallback_text = "🏆 Your Active Subscriptions\n\nThere was an issue displaying your subscriptions. Please try again or contact support."
                keyboard = [[InlineKeyboardButton("📋 View Plans", callback_data="view_plans")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(fallback_text, reply_markup=reply_markup)
            except:
                pass  # If even fallback fails, let it go
        finally:
            db.close()
    
    async def send_notification(self, match: Match, notification_type: str):
        """Send notification directly to subscribed users"""
        db = SessionLocal()
        
        try:
            # Prepare notification content
            if notification_type == 'match_start':
                text = self._format_match_start_notification(match)
                target_users = self._get_all_active_users(db)  # Free notifications to all users
                log_type = 'free'
                
            elif notification_type == 'halftime_trailing':
                text = self._format_halftime_notification(match)
                target_users = self._get_subscribed_users(db, match.sport)  # Premium notifications to subscribers
                log_type = 'premium'
            
            sent_count = 0
            failed_count = 0
            
            # Send to individual users
            for user in target_users:
                try:
                    await self.app.bot.send_message(
                        chat_id=user.telegram_id,
                        text=text,
                        parse_mode='Markdown'
                    )
                    sent_count += 1
                    logger.info(f"Notification sent to user {user.telegram_id}")
                    
                except Exception as e:
                    # If Markdown fails, try without Markdown
                    if "can't parse entities" in str(e).lower():
                        try:
                            plain_text = text.replace('*', '').replace('_', '').replace('[', '').replace(']', '').replace('`', '')
                            await self.app.bot.send_message(
                                chat_id=user.telegram_id,
                                text=plain_text
                            )
                            sent_count += 1
                            logger.warning(f"Notification sent to user {user.telegram_id} without Markdown due to parsing error")
                        except Exception as fallback_error:
                            failed_count += 1
                            logger.error(f"Failed to send notification to user {user.telegram_id} even without Markdown: {str(fallback_error)}")
                    else:
                        failed_count += 1
                        logger.error(f"Failed to send notification to user {user.telegram_id}: {str(e)}")
            
            # Log notification summary
            log = NotificationLog(
                match_id=match.id,
                channel_type=log_type,
                notification_type=notification_type,
                content={'text': text, 'sent_count': sent_count, 'failed_count': failed_count},
                success=sent_count > 0
            )
            db.add(log)
            db.commit()
            
            logger.info(f"Notification summary - Sent: {sent_count}, Failed: {failed_count}")
            
            # Mark notification as sent
            await odds_tracker.mark_notification_sent(match.id, notification_type)
                
        finally:
            db.close()
    
    def _get_all_active_users(self, db) -> List[User]:
        """Get all active users for free notifications"""
        return db.query(User).filter_by(is_active=True).all()
    
    def _get_subscribed_users(self, db, sport: str) -> List[User]:
        """Get users subscribed to a specific sport for premium notifications"""
        from sqlalchemy import and_, or_, text
        
        # For PostgreSQL JSON column, use proper JSON contains operator
        subscribed_users = db.query(User).join(Subscription).filter(
            and_(
                Subscription.is_active == True,
                Subscription.end_date > datetime.utcnow(),
                or_(
                    # Full access plan includes all sports
                    Subscription.plan_type == 'full_access',
                    # Use PostgreSQL JSON contains operator (?? for text array contains)
                    text(f"subscriptions.sports::jsonb ? '{sport}'")
                )
            )
        ).all()
        
        return subscribed_users
    
    def _format_match_start_notification(self, match: Match) -> str:
        """Format match start notification"""
        sport_emoji = {'tennis': '🎾', 'basketball': '🏀', 'handball': '🤾'}.get(match.sport, '🏆')
        
        # Escape special Markdown characters in team and league names
        def escape_markdown(text):
            if not text:
                return ""
            return text.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]').replace('`', '\\`')
        
        home_team = escape_markdown(match.home_team)
        away_team = escape_markdown(match.away_team)
        league_name = escape_markdown(match.league_name)
        favorite_name = home_team if match.pre_match_favorite == 'home' else away_team
        
        # Safe odds formatting to prevent None errors
        home_odds = match.pre_match_home_odds if match.pre_match_home_odds is not None else 0.0
        away_odds = match.pre_match_away_odds if match.pre_match_away_odds is not None else 0.0
        
        text = (
            f"{sport_emoji} **MATCH STARTING SOON**\n\n"
            f"**{home_team} vs {away_team}**\n"
            f"League: {league_name}\n"
            f"Sport: {match.sport.capitalize()}\n\n"
            f"**Pre-match Odds:**\n"
            f"• {home_team}: {home_odds:.2f}\n"
            f"• {away_team}: {away_odds:.2f}\n"
        )
        
        if match.pre_match_draw_odds is not None:
            text += f"• Draw: {match.pre_match_draw_odds:.2f}\n"
        
        text += f"\n**Favorite:** {favorite_name}"
        
        return text
    
    def _format_halftime_notification(self, match: Match) -> str:
        """Format halftime trailing notification"""
        sport_emoji = {'tennis': '🎾', 'basketball': '🏀', 'handball': '🤾'}.get(match.sport, '🏆')
        
        # Escape special Markdown characters in team and league names
        def escape_markdown(text):
            if not text:
                return ""
            return text.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]').replace('`', '\\`')
        
        home_team = escape_markdown(match.home_team)
        away_team = escape_markdown(match.away_team)
        league_name = escape_markdown(match.league_name)
        favorite_team = home_team if match.pre_match_favorite == 'home' else away_team
        
        if match.sport == 'tennis':
            period_text = "FIRST SET"
        else:
            period_text = "HALFTIME"
        
        # Safe odds formatting to prevent None errors
        pre_match_fav_odds = (match.pre_match_home_odds if match.pre_match_favorite == 'home' 
                             else match.pre_match_away_odds) if match.pre_match_home_odds is not None and match.pre_match_away_odds is not None else 0.0
        
        halftime_home_odds = match.halftime_home_odds if match.halftime_home_odds is not None else 0.0
        halftime_away_odds = match.halftime_away_odds if match.halftime_away_odds is not None else 0.0
        
        text = (
            f"🚨 **FAVORITE TRAILING AT {period_text}** 🚨\n\n"
            f"{sport_emoji} **{home_team} vs {away_team}**\n"
            f"League: {league_name}\n\n"
            f"**Current Score:**\n"
            f"{home_team}: {match.current_score_home or 0}\n"
            f"{away_team}: {match.current_score_away or 0}\n\n"
            f"**Pre-match Favorite:** {favorite_team}\n"
            f"**Pre-match Odds:** {pre_match_fav_odds:.2f}\n\n"
            f"**Current Live Odds:**\n"
            f"• {home_team}: {halftime_home_odds:.2f}\n"
            f"• {away_team}: {halftime_away_odds:.2f}\n"
        )
        
        if match.halftime_draw_odds is not None:
            text += f"• Draw: {match.halftime_draw_odds:.2f}\n"
        
        text += "\n💡 The favorite is now trailing - potential value opportunity!"
        
        return text
    
    async def notification_loop(self):
        """Continuous loop to check and send notifications"""
        while True:
            try:
                # Get matches needing notifications
                matches = await odds_tracker.get_matches_for_notification()
                
                # Send match start notifications
                for match in matches['match_start']:
                    await self.send_notification(match, 'match_start')
                
                # Send halftime trailing notifications
                for match in matches['halftime_trailing']:
                    # Only send to users subscribed to this sport
                    await self.send_notification(match, 'halftime_trailing')
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in notification loop: {str(e)}")
                await asyncio.sleep(60)
    
    async def post_init(self, application: Application) -> None:
        """Initialize bot after application is created"""
        self.app = application
        
        # Start only lightweight notification loop
        # Odds tracking is handled by separate data_service.py
        logger.info("Bot initialized - starting notification service...")
        
        # Only start lightweight notification loop
        self.notification_task = asyncio.create_task(self._start_notifications_with_delay())
        
        logger.info("✅ Bot ready to handle commands")
    
    async def _start_notifications_with_delay(self):
        """Start notification loop after a delay"""
        await asyncio.sleep(5)  # Short delay for bot initialization
        logger.info("Starting notification loop...")
        await self.notification_loop()

    def run(self):
        """Run the bot with optimized polling"""
        # Initialize database
        init_db()
        
        # Create application
        application = Application.builder().token(env_config.TELEGRAM_BOT_TOKEN).post_init(self.post_init).build()
        self.app = application
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("admin", self.admin_panel))
        
        # Callback query handlers
        application.add_handler(CallbackQueryHandler(self.view_plans, pattern="^view_plans$"))
        application.add_handler(CallbackQueryHandler(self.my_subscriptions, pattern="^my_subscriptions$"))
        application.add_handler(CallbackQueryHandler(self.show_duration_selection, pattern="^plan_"))
        application.add_handler(CallbackQueryHandler(self.handle_duration_selection, pattern="^duration_"))
        application.add_handler(CallbackQueryHandler(self.handle_single_sport_selection, pattern="^single_sport_"))
        application.add_handler(CallbackQueryHandler(self.handle_sport_toggle, pattern="^toggle_sport_"))
        application.add_handler(CallbackQueryHandler(self.confirm_sport_selection, pattern="^confirm_sport_"))
        application.add_handler(CallbackQueryHandler(self.start, pattern="^back_to_main$"))
        
        # Admin callback handlers
        application.add_handler(CallbackQueryHandler(self.admin_users, pattern="^admin_users$"))
        application.add_handler(CallbackQueryHandler(self.admin_payments, pattern="^admin_payments$"))
        application.add_handler(CallbackQueryHandler(self.admin_matches, pattern="^admin_matches$"))
        application.add_handler(CallbackQueryHandler(self.admin_notifications, pattern="^admin_notifications$"))
        application.add_handler(CallbackQueryHandler(self.admin_system_status, pattern="^admin_system$"))
        application.add_handler(CallbackQueryHandler(self.admin_back, pattern="^admin_back$"))
        application.add_handler(CallbackQueryHandler(self.admin_add_test_matches, pattern="^admin_add_test_matches$"))
        
        # New admin handlers
        application.add_handler(CallbackQueryHandler(self.admin_revenue, pattern="^admin_revenue$"))
        application.add_handler(CallbackQueryHandler(self.admin_notification_stats, pattern="^admin_notification_stats$"))
        application.add_handler(CallbackQueryHandler(self.admin_stats, pattern="^admin_stats$"))
        
        # Use optimized polling (fast response, no heavy background tasks in bot)
        logger.info("🚀 Starting bot with optimized polling...")
        logger.info("📊 Data fetching runs separately in data_service.py")
        
        application.run_polling(
            allowed_updates=Update.ALL_TYPES, 
            drop_pending_updates=True,
            poll_interval=1.0,  # Fast polling for responsive commands
            timeout=10  # Quick timeout for better responsiveness
        )

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin command - Admin panel with statistics and management"""
        user_id = str(update.effective_user.id)
        
        # Validate that we have a proper message update
        if not update.message:
            logger.warning("Received admin command without message object")
            return
        
        # Check if user is admin
        if user_id != env_config.ADMIN_TELEGRAM_ID:
            await update.message.reply_text("❌ Access denied. You are not authorized to use admin commands.")
            return
        
        db = SessionLocal()
        try:
            # Get statistics
            total_users = db.query(User).count()
            active_subs = db.query(Subscription).filter_by(is_active=True).filter(
                Subscription.end_date > datetime.utcnow()
            ).count()
            total_matches = db.query(Match).count()
            pending_payments = db.query(Payment).filter_by(status='pending').count()
            completed_payments = db.query(Payment).filter_by(status='completed').count()
            
            # Recent notifications
            recent_notifications = db.query(NotificationLog).order_by(
                NotificationLog.sent_at.desc()
            ).limit(5).all()
            
            keyboard = [
                [InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
                [InlineKeyboardButton("💳 Payment Management", callback_data="admin_payments")],
                [InlineKeyboardButton("⚽ Match Management", callback_data="admin_matches")],
                [InlineKeyboardButton("🔔 Notification Logs", callback_data="admin_notifications")],
                [InlineKeyboardButton("📊 Detailed Stats", callback_data="admin_stats")],
                [InlineKeyboardButton("🔧 System Status", callback_data="admin_system")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            admin_text = f"""
🔧 *Admin Panel* 

📊 *Quick Stats:*
• Total Users: {total_users}
• Active Subscriptions: {active_subs}
• Total Matches: {total_matches}
• Pending Payments: {pending_payments}
• Completed Payments: {completed_payments}

🔔 *Recent Notifications:*
{self._format_recent_notifications(recent_notifications)}

Select an option below for detailed management:
"""
            
            try:
                await update.message.reply_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as markdown_error:
                logger.error(f"Markdown parsing error in admin_panel: {str(markdown_error)}")
                # Fallback to plain text if Markdown fails
                fallback_text = admin_text.replace('*', '').replace('_', '').replace('[', '').replace(']', '')
                await update.message.reply_text(fallback_text, reply_markup=reply_markup)
            
        finally:
            db.close()
    
    async def admin_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user management panel"""
        query = update.callback_query
        await query.answer()
        
        db = SessionLocal()
        try:
            users = db.query(User).order_by(User.created_at.desc()).limit(10).all()
            
            def safe_escape(text):
                """Safely escape Markdown special characters"""
                if not text:
                    return "Unknown"
                # Escape all Markdown special characters
                chars_to_escape = ['*', '_', '`', '[', ']', '(', ')', '#', '+', '-', '.', '!', '\\']
                for char in chars_to_escape:
                    text = text.replace(char, f'\\{char}')
                return text
            
            text = "👥 **User Management**\n\n**Recent Users:**\n"
            for user in users:
                active_sub = db.query(Subscription).filter_by(
                    user_id=user.id, is_active=True
                ).filter(Subscription.end_date > datetime.utcnow()).first()
                
                status = "🟢 Subscribed" if active_sub else "🔴 Free"
                safe_first_name = safe_escape(user.first_name or 'Unknown')
                safe_username = safe_escape(user.username or 'no_username')
                text += f"• {safe_first_name} (@{safe_username}) \\- {status}\n"
            
            keyboard = [
                [InlineKeyboardButton("📊 Export Users", callback_data="admin_export_users")],
                [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Markdown error in admin_users: {str(e)}")
                # Fallback to plain text if Markdown fails
                plain_text = text.replace('*', '').replace('_', '').replace('\\', '').replace('[', '').replace(']', '')
                await query.edit_message_text(plain_text, reply_markup=reply_markup)
            
        finally:
            db.close()
    
    async def admin_payments(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show payment management panel"""
        query = update.callback_query
        await query.answer()
        
        db = SessionLocal()
        try:
            recent_payments = db.query(Payment).order_by(Payment.created_at.desc()).limit(10).all()
            
            def safe_escape(text):
                """Safely escape Markdown special characters"""
                if not text:
                    return "Unknown"
                chars_to_escape = ['*', '_', '`', '[', ']', '(', ')', '#', '+', '-', '.', '!', '\\']
                for char in chars_to_escape:
                    text = text.replace(char, f'\\{char}')
                return text
            
            text = "💳 **Payment Management**\n\n**Recent Payments:**\n"
            for payment in recent_payments:
                user = db.query(User).filter_by(id=payment.user_id).first()
                status_emoji = {"completed": "✅", "pending": "⏳", "failed": "❌"}.get(payment.status, "❓")
                safe_name = safe_escape(user.first_name if user else 'Unknown')
                safe_status = safe_escape(payment.status or 'unknown')
                text += f"• {safe_name} \\- €{payment.amount} \\- {status_emoji} {safe_status}\n"
            
            keyboard = [
                [InlineKeyboardButton("💰 Revenue Stats", callback_data="admin_revenue")],
                [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Markdown error in admin_payments: {str(e)}")
                # Fallback to plain text if Markdown fails
                plain_text = text.replace('*', '').replace('_', '').replace('\\', '').replace('[', '').replace(']', '')
                await query.edit_message_text(plain_text, reply_markup=reply_markup)
            
        finally:
            db.close()
    
    async def admin_matches(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show match management panel"""
        query = update.callback_query
        await query.answer()
        
        db = SessionLocal()
        try:
            # Get matches by sport for comprehensive overview
            tennis_matches = db.query(Match).filter_by(sport='tennis').order_by(Match.updated_at.desc()).limit(5).all()
            basketball_matches = db.query(Match).filter_by(sport='basketball').order_by(Match.updated_at.desc()).limit(5).all()
            handball_matches = db.query(Match).filter_by(sport='handball').order_by(Match.updated_at.desc()).limit(5).all()
            
            # Get live matches from all sports
            live_matches = db.query(Match).filter(Match.status.in_(['live', 'halftime', 'scheduled'])).order_by(Match.start_time.desc()).limit(8).all()
            
            # Get recent matches with trailing favorites
            trailing_matches = db.query(Match).filter_by(favorite_trailing_at_halftime=True).order_by(
                Match.updated_at.desc()
            ).limit(5).all()
            
            def format_match(match):
                """Helper function to format match display"""
                emoji = {'tennis': '🎾', 'basketball': '🏀', 'handball': '🤾'}.get(match.sport, '⚽')
                safe_home = match.home_team.replace('*', '\\*').replace('_', '\\_') if match.home_team else "Unknown"
                safe_away = match.away_team.replace('*', '\\*').replace('_', '\\_') if match.away_team else "Unknown"
                status_emoji = {'live': '🔴', 'halftime': '⏸️', 'scheduled': '⏰', 'finished': '✅'}.get(match.status, '❓')
                return f"• {emoji} {safe_home} vs {safe_away} {status_emoji}"
            
            text = "⚽ **Match Management - All Sports**\n\n"
            
            # Live/Scheduled Matches Section
            text += "🔴 **Live & Upcoming Matches:**\n"
            if live_matches:
                for match in live_matches:
                    text += format_match(match) + f" ({match.status})\n"
            else:
                text += "No live/scheduled matches currently\n"
            
            # Sports Breakdown
            text += "\n📊 **Recent Matches by Sport:**\n"
            
            # Tennis
            text += "\n🎾 **Tennis:**\n"
            if tennis_matches:
                for match in tennis_matches:
                    text += format_match(match) + f" ({match.status})\n"
            else:
                text += "No recent tennis matches\n"
            
            # Basketball  
            text += "\n🏀 **Basketball:**\n"
            if basketball_matches:
                for match in basketball_matches:
                    text += format_match(match) + f" ({match.status})\n"
            else:
                text += "No recent basketball matches\n"
            
            # Handball
            text += "\n🤾 **Handball:**\n"
            if handball_matches:
                for match in handball_matches:
                    text += format_match(match) + f" ({match.status})\n"
            else:
                text += "No recent handball matches\n"
            
            # Trailing Favorites Section
            text += "\n🚨 **Recent Trailing Favorites:**\n"
            if trailing_matches:
                for match in trailing_matches:
                    text += format_match(match) + f" (Sport: {match.sport.title()})\n"
            else:
                text += "No recent trailing favorites\n"
            
            # Statistics
            total_matches = db.query(Match).count()
            matches_by_sport = {
                'tennis': db.query(Match).filter_by(sport='tennis').count(),
                'basketball': db.query(Match).filter_by(sport='basketball').count(),
                'handball': db.query(Match).filter_by(sport='handball').count()
            }
            
            text += f"\n📈 **Database Stats:**\n"
            text += f"• Total Matches: {total_matches}\n"
            text += f"• Tennis: {matches_by_sport['tennis']}\n"
            text += f"• Basketball: {matches_by_sport['basketball']}\n"
            text += f"• Handball: {matches_by_sport['handball']}\n"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Force Match Update", callback_data="admin_force_update")],
                [InlineKeyboardButton("📊 Detailed Stats", callback_data="admin_match_stats")],
                [InlineKeyboardButton("🧪 Add Test Matches", callback_data="admin_add_test_matches")],
                [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        finally:
            db.close()
    
    async def admin_notifications(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show notification management panel"""
        query = update.callback_query
        await query.answer()
        
        db = SessionLocal()
        try:
            recent_logs = db.query(NotificationLog).order_by(NotificationLog.sent_at.desc()).limit(15).all()
            
            text = "🔔 **Notification Logs**\n\n"
            if not recent_logs:
                text += "No recent notifications found.\n"
            else:
                for log in recent_logs:
                    status = "✅" if log.success else "❌"
                    match = db.query(Match).filter_by(id=log.match_id).first()
                    if match:
                        # Better Markdown escaping for team names
                        def safe_escape(text):
                            if not text:
                                return "Unknown"
                            # Escape all Markdown special characters
                            chars_to_escape = ['*', '_', '`', '[', ']', '(', ')', '#', '+', '-', '.', '!']
                            for char in chars_to_escape:
                                text = text.replace(char, f'\\{char}')
                            return text
                        
                        safe_home = safe_escape(match.home_team)
                        safe_away = safe_escape(match.away_team)
                        match_name = f"{safe_home} vs {safe_away}"
                    else:
                        match_name = "Unknown Match"
                    
                    sent_count = log.content.get('sent_count', 0) if isinstance(log.content, dict) else 0
                    
                    # Escape notification type
                    safe_notif_type = log.notification_type.replace('_', '\\_') if log.notification_type else "Unknown"
                    
                    text += f"• {status} {safe_notif_type} \\- {match_name} (Sent: {sent_count})\n"
            
            keyboard = [
                [InlineKeyboardButton("📊 Notification Stats", callback_data="admin_notification_stats")],
                [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Markdown error in admin_notifications: {str(e)}")
                # Fallback to plain text
                plain_text = text.replace('*', '').replace('_', '').replace('\\', '').replace('[', '').replace(']', '')
                await query.edit_message_text(plain_text, reply_markup=reply_markup)
            
        finally:
            db.close()
    
    async def admin_system_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show system status"""
        query = update.callback_query
        await query.answer()
        
        import os
        import psutil
        
        # Get system info
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Check if ngrok is running
        ngrok_status = "🟢 Running" if os.path.exists('/tmp/ngrok.pid') else "🔴 Not detected"
        
        # Database status
        db = SessionLocal()
        try:
            db.execute("SELECT 1")
            db_status = "🟢 Connected"
        except:
            db_status = "🔴 Error"
        finally:
            db.close()
        
        text = f"""
🔧 **System Status**

**System Resources:**
• CPU Usage: {cpu_percent}%
• Memory: {memory.percent}% ({memory.used // (1024**3):.1f}GB / {memory.total // (1024**3):.1f}GB)
• Disk: {disk.percent}% ({disk.used // (1024**3):.1f}GB / {disk.total // (1024**3):.1f}GB)

**Services:**
• Database: {db_status}
• Ngrok: {ngrok_status}
• Bot: 🟢 Running

**Configuration:**
• API Token: {'✅ Set' if env_config.API_TOKEN != 'YOUR_API_TOKEN' else '⚠️ Default'}
• PayPal: {'✅ Configured' if env_config.PAYPAL_CLIENT_ID != 'YOUR_PAYPAL_SANDBOX_CLIENT_ID' else '❌ Not set'}
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 Restart Services", callback_data="admin_restart")],
            [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    def _format_recent_notifications(self, notifications):
        """Format recent notifications for display"""
        if not notifications:
            return "No recent notifications"
        
        def escape_markdown(text):
            if not text:
                return ""
            return str(text).replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]').replace('`', '\\`')
        
        text = ""
        for notif in notifications:
            status = "✅" if notif.success else "❌"
            sent_count = notif.content.get('sent_count', 0) if isinstance(notif.content, dict) else 0
            # Escape notification type to prevent Markdown parsing issues and handle None values
            safe_notif_type = escape_markdown(notif.notification_type) if notif.notification_type else "Unknown"
            text += f"{status} {safe_notif_type} (Sent: {sent_count})\n"
        
        return text
    
    async def admin_back(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to main admin panel"""
        # Simulate the original admin command
        query = update.callback_query
        await query.answer()
        
        # Call admin panel but modify to edit message instead of send new
        user_id = str(query.from_user.id)
        
        if user_id != env_config.ADMIN_TELEGRAM_ID:
            await query.edit_message_text("❌ Access denied.")
            return
        
        db = SessionLocal()
        try:
            # Get statistics (same as admin_panel)
            total_users = db.query(User).count()
            active_subs = db.query(Subscription).filter_by(is_active=True).filter(
                Subscription.end_date > datetime.utcnow()
            ).count()
            total_matches = db.query(Match).count()
            pending_payments = db.query(Payment).filter_by(status='pending').count()
            completed_payments = db.query(Payment).filter_by(status='completed').count()
            
            recent_notifications = db.query(NotificationLog).order_by(
                NotificationLog.sent_at.desc()
            ).limit(5).all()
            
            keyboard = [
                [InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
                [InlineKeyboardButton("💳 Payment Management", callback_data="admin_payments")],
                [InlineKeyboardButton("⚽ Match Management", callback_data="admin_matches")],
                [InlineKeyboardButton("🔔 Notification Logs", callback_data="admin_notifications")],
                [InlineKeyboardButton("📊 Detailed Stats", callback_data="admin_stats")],
                [InlineKeyboardButton("🔧 System Status", callback_data="admin_system")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            admin_text = f"""
🔧 *Admin Panel* 

📊 *Quick Stats:*
• Total Users: {total_users}
• Active Subscriptions: {active_subs}
• Total Matches: {total_matches}
• Pending Payments: {pending_payments}
• Completed Payments: {completed_payments}

🔔 *Recent Notifications:*
{self._format_recent_notifications(recent_notifications)}

Select an option below for detailed management:
"""
            
            try:
                await query.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as markdown_error:
                logger.error(f"Markdown parsing error in admin_panel: {str(markdown_error)}")
                # Fallback to plain text if Markdown fails
                fallback_text = admin_text.replace('*', '').replace('_', '').replace('[', '').replace(']', '')
                await query.edit_message_text(fallback_text, reply_markup=reply_markup)
            
        finally:
            db.close()

    async def admin_add_test_matches(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add test matches for basketball and handball for demonstration"""
        query = update.callback_query
        await query.answer()
        
        db = SessionLocal()
        try:
            from datetime import datetime, timedelta
            
            # Add test basketball matches
            basketball_matches = [
                {
                    'event_id': 'TEST_BB_001',
                    'sport': 'basketball',
                    'home_team': 'Lakers',
                    'away_team': 'Warriors',
                    'league_name': 'NBA',
                    'status': 'scheduled',
                    'pre_match_home_odds': 1.85,
                    'pre_match_away_odds': 1.95,
                    'pre_match_favorite': 'home'
                },
                {
                    'event_id': 'TEST_BB_002', 
                    'sport': 'basketball',
                    'home_team': 'Bulls',
                    'away_team': 'Celtics',
                    'league_name': 'NBA',
                    'status': 'live',
                    'pre_match_home_odds': 2.10,
                    'pre_match_away_odds': 1.75,
                    'pre_match_favorite': 'away',
                    'current_score_home': 45,
                    'current_score_away': 52
                }
            ]
            
            # Add test handball matches
            handball_matches = [
                {
                    'event_id': 'TEST_HB_001',
                    'sport': 'handball',
                    'home_team': 'THW Kiel',
                    'away_team': 'PSG Handball',
                    'league_name': 'Champions League',
                    'status': 'scheduled',
                    'pre_match_home_odds': 1.90,
                    'pre_match_away_odds': 1.85,
                    'pre_match_favorite': 'away'
                },
                {
                    'event_id': 'TEST_HB_002',
                    'sport': 'handball', 
                    'home_team': 'Barcelona',
                    'away_team': 'Flensburg',
                    'league_name': 'Champions League',
                    'status': 'halftime',
                    'pre_match_home_odds': 1.55,
                    'pre_match_away_odds': 2.40,
                    'pre_match_favorite': 'home',
                    'current_score_home': 12,
                    'current_score_away': 15,
                    'favorite_trailing_at_halftime': True
                }
            ]
            
            added_count = 0
            for matches, sport_name in [(basketball_matches, 'Basketball'), (handball_matches, 'Handball')]:
                for match_data in matches:
                    # Check if test match already exists
                    existing = db.query(Match).filter_by(event_id=match_data['event_id']).first()
                    if not existing:
                        match = Match(
                            event_id=match_data['event_id'],
                            sport=match_data['sport'],
                            home_team=match_data['home_team'],
                            away_team=match_data['away_team'],
                            league_name=match_data['league_name'],
                            status=match_data['status'],
                            start_time=datetime.utcnow() + timedelta(hours=2),
                            pre_match_home_odds=match_data['pre_match_home_odds'],
                            pre_match_away_odds=match_data['pre_match_away_odds'],
                            pre_match_favorite=match_data['pre_match_favorite'],
                            current_score_home=match_data.get('current_score_home', 0),
                            current_score_away=match_data.get('current_score_away', 0),
                            favorite_trailing_at_halftime=match_data.get('favorite_trailing_at_halftime', False)
                        )
                        db.add(match)
                        added_count += 1
            
            db.commit()
            
            text = f"🧪 **Test Matches Added**\n\n"
            text += f"Successfully added {added_count} test matches to demonstrate all sports.\n\n"
            text += "• 2 Basketball matches (Lakers vs Warriors, Bulls vs Celtics)\n"
            text += "• 2 Handball matches (THW Kiel vs PSG, Barcelona vs Flensburg)\n\n"
            text += "You can now go back to Match Management to see all sports!"
            
            keyboard = [
                [InlineKeyboardButton("⚽ Back to Match Management", callback_data="admin_matches")],
                [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error adding test matches: {str(e)}")
            await query.edit_message_text(
                f"❌ Error adding test matches: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_matches")]])
            )
        finally:
            db.close()

    async def admin_revenue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show revenue statistics"""
        query = update.callback_query
        await query.answer()
        
        db = SessionLocal()
        try:
            # Get revenue statistics
            total_revenue = db.query(Payment).filter_by(status='completed').with_entities(
                db.func.sum(Payment.amount)
            ).scalar() or 0
            
            pending_revenue = db.query(Payment).filter_by(status='pending').with_entities(
                db.func.sum(Payment.amount)
            ).scalar() or 0
            
            # Revenue by plan type
            revenue_by_plan = db.query(Payment.plan_type, db.func.sum(Payment.amount)).filter_by(
                status='completed'
            ).group_by(Payment.plan_type).all()
            
            # Recent payments
            recent_payments = db.query(Payment).filter_by(status='completed').order_by(
                Payment.updated_at.desc()
            ).limit(10).all()
            
            text = f"💰 **Revenue Statistics**\n\n"
            text += f"**Total Revenue**: €{total_revenue:.2f}\n"
            text += f"**Pending Revenue**: €{pending_revenue:.2f}\n\n"
            
            text += "**Revenue by Plan Type**:\n"
            for plan_type, revenue in revenue_by_plan:
                plan_name = plan_type.replace('_', ' ').title()
                text += f"• {plan_name}: €{revenue:.2f}\n"
            
            text += f"\n**Recent Payments** (Last 10):\n"
            for payment in recent_payments:
                user = db.query(User).filter_by(id=payment.user_id).first()
                user_name = user.first_name if user and user.first_name else "Unknown"
                # Escape user name safely
                safe_name = user_name.replace('*', '\\*').replace('_', '\\_')
                text += f"• {safe_name}: €{payment.amount} ({payment.plan_type})\n"
            
            keyboard = [
                [InlineKeyboardButton("📊 Export Revenue Data", callback_data="admin_export_revenue")],
                [InlineKeyboardButton("🔙 Back to Payments", callback_data="admin_payments")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Markdown error in admin_revenue: {str(e)}")
                # Fallback to plain text
                plain_text = text.replace('*', '').replace('_', '').replace('\\', '')
                await query.edit_message_text(plain_text, reply_markup=reply_markup)
            
        finally:
            db.close()
    
    async def admin_notification_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed notification statistics"""
        query = update.callback_query
        await query.answer()
        
        db = SessionLocal()
        try:
            # Get notification statistics
            total_notifications = db.query(NotificationLog).count()
            successful_notifications = db.query(NotificationLog).filter_by(success=True).count()
            failed_notifications = db.query(NotificationLog).filter_by(success=False).count()
            
            # Notifications by type
            notifications_by_type = db.query(
                NotificationLog.notification_type,
                db.func.count(NotificationLog.id)
            ).group_by(NotificationLog.notification_type).all()
            
            # Notifications by channel type
            notifications_by_channel = db.query(
                NotificationLog.channel_type,
                db.func.count(NotificationLog.id)
            ).group_by(NotificationLog.channel_type).all()
            
            # Recent notification summary
            recent_logs = db.query(NotificationLog).order_by(
                NotificationLog.sent_at.desc()
            ).limit(5).all()
            
            text = f"📊 **Notification Statistics**\n\n"
            text += f"**Total Notifications**: {total_notifications}\n"
            text += f"**Successful**: {successful_notifications}\n"
            text += f"**Failed**: {failed_notifications}\n"
            text += f"**Success Rate**: {(successful_notifications/total_notifications*100):.1f}% \n\n" if total_notifications > 0 else "**Success Rate**: N/A\n\n"
            
            text += "**Notifications by Type**:\n"
            for notif_type, count in notifications_by_type:
                safe_type = notif_type.replace('_', ' ').title() if notif_type else "Unknown"
                text += f"• {safe_type}: {count}\n"
            
            text += "\n**Notifications by Channel**:\n"
            for channel_type, count in notifications_by_channel:
                channel_name = "Premium" if channel_type == "premium" else "Free"
                text += f"• {channel_name}: {count}\n"
            
            text += f"\n**Recent Activity** (Last 5):\n"
            for log in recent_logs:
                status = "✅" if log.success else "❌"
                sent_count = log.content.get('sent_count', 0) if isinstance(log.content, dict) else 0
                safe_type = log.notification_type.replace('_', ' ') if log.notification_type else "Unknown"
                text += f"• {status} {safe_type} (Sent: {sent_count})\n"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin_notification_stats")],
                [InlineKeyboardButton("🔙 Back to Notifications", callback_data="admin_notifications")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in admin_notification_stats: {str(e)}")
            # Simple fallback message
            error_text = f"📊 Notification Statistics\n\nError loading statistics: {str(e)}\n\nPlease try again."
            keyboard = [
                [InlineKeyboardButton("🔙 Back to Notifications", callback_data="admin_notifications")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(error_text, reply_markup=reply_markup)
        finally:
            db.close()
    
    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed system statistics"""
        query = update.callback_query
        await query.answer()
        
        db = SessionLocal()
        try:
            # User statistics
            total_users = db.query(User).count()
            active_users = db.query(User).filter_by(is_active=True).count()
            
            # Subscription statistics
            total_subs = db.query(Subscription).count()
            active_subs = db.query(Subscription).filter_by(is_active=True).filter(
                Subscription.end_date > datetime.utcnow()
            ).count()
            expired_subs = db.query(Subscription).filter(
                Subscription.end_date <= datetime.utcnow()
            ).count()
            
            # Subscription by plan type
            subs_by_plan = db.query(
                Subscription.plan_type,
                db.func.count(Subscription.id)
            ).filter_by(is_active=True).filter(
                Subscription.end_date > datetime.utcnow()
            ).group_by(Subscription.plan_type).all()
            
            # Payment statistics
            total_payments = db.query(Payment).count()
            completed_payments = db.query(Payment).filter_by(status='completed').count()
            pending_payments = db.query(Payment).filter_by(status='pending').count()
            failed_payments = db.query(Payment).filter_by(status='failed').count()
            
            # Match statistics
            total_matches = db.query(Match).count()
            live_matches = db.query(Match).filter(Match.status.in_(['live', 'halftime'])).count()
            
            # Revenue
            total_revenue = db.query(Payment).filter_by(status='completed').with_entities(
                db.func.sum(Payment.amount)
            ).scalar() or 0
            
            text = f"📊 **Detailed System Statistics**\n\n"
            
            text += f"**👥 Users**:\n"
            text += f"• Total: {total_users}\n"
            text += f"• Active: {active_users}\n\n"
            
            text += f"**🏆 Subscriptions**:\n"
            text += f"• Total: {total_subs}\n"
            text += f"• Active: {active_subs}\n"
            text += f"• Expired: {expired_subs}\n\n"
            
            text += f"**Active Plans**:\n"
            for plan_type, count in subs_by_plan:
                plan_name = plan_type.replace('_', ' ').title()
                text += f"• {plan_name}: {count}\n"
            
            text += f"\n**💳 Payments**:\n"
            text += f"• Total: {total_payments}\n"
            text += f"• Completed: {completed_payments}\n"
            text += f"• Pending: {pending_payments}\n"
            text += f"• Failed: {failed_payments}\n"
            
            text += f"\n**⚽ Matches**:\n"
            text += f"• Total: {total_matches}\n"
            text += f"• Currently Live: {live_matches}\n"
            
            text += f"\n**💰 Revenue**:\n"
            text += f"• Total: €{total_revenue:.2f}\n"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin_stats")],
                [InlineKeyboardButton("📊 Export All Data", callback_data="admin_export_all")],
                [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in admin_stats: {str(e)}")
            # Simple fallback message
            error_text = f"📊 System Statistics\n\nError loading statistics: {str(e)}\n\nPlease try again."
            keyboard = [
                [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(error_text, reply_markup=reply_markup)
        finally:
            db.close()

if __name__ == "__main__":
    bot = BettingBot()
    bot.run() 