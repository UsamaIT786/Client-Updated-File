import logging
import asyncio
from datetime import datetime, timedelta, UTC
from typing import List, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from database import User, Subscription, Payment, NotificationLog, Match, init_db, SessionLocal, get_all_plans
from paypal_integration import paypal_service
from odds_tracker import odds_tracker
import env_config

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_dynamic_prices() -> Dict:
    """
    Fetch plan prices from the database and calculate multi-month discounts.
    """
    try:
        db_plans = get_all_plans()
        if not db_plans:
            logger.warning("No plans found in DB. Falling back to env_config.PRICING.")
            return env_config.PRICING

        pricing = {}
        for plan in db_plans:
            base_price = plan['price']
            # Apply a consistent discount structure for multi-month plans
            # 3 months = ~10% discount
            # 6 months = ~15% discount
            pricing[plan['name']] = {
                1: base_price,
                3: round(base_price * 3 * 0.9),
                6: round(base_price * 6 * 0.85)
            }
        return pricing
    except Exception as e:
        logger.error(f"Error fetching dynamic prices: {e}. Falling back to env_config.PRICING.")
        return env_config.PRICING

class BettingBot:
    def __init__(self):
        self.app = None
        self.premium_channel_id = env_config.PREMIUM_CHANNEL_ID
        self.free_channel_id = env_config.FREE_CHANNEL_ID
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command and back to main callbacks"""
        user = update.effective_user
        
        # Handle both direct messages and callback queries
        if update.callback_query:
            # Called from a callback query (like "Back to main")
            query = update.callback_query
            await query.answer()
            is_callback = True
        elif update.message:
            # Called from a direct /start command
            is_callback = False
        else:
            logger.warning("Received start command without message or callback query object")
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
            
            # Send appropriate response based on how we were called
            if is_callback:
                await query.edit_message_text(welcome_text, reply_markup=reply_markup)
            else:
                await update.message.reply_text(welcome_text, reply_markup=reply_markup)
            
        finally:
            db.close()
    
    async def view_plans(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display available subscription plans"""
        query = update.callback_query
        await query.answer()

        pricing = get_dynamic_prices()
        
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
            f"• 1 Month: €{pricing.get('single_sport', {}).get(1, 'N/A')}\n"
            f"• 3 Months: €{pricing.get('single_sport', {}).get(3, 'N/A')}\n"
            f"• 6 Months: €{pricing.get('single_sport', {}).get(6, 'N/A')}\n\n"
            "**🔥 2 Combined Sports**\n"
            f"• 1 Month: €{pricing.get('two_sports', {}).get(1, 'N/A')}\n"
            f"• 3 Months: €{pricing.get('two_sports', {}).get(3, 'N/A')}\n"
            f"• 6 Months: €{pricing.get('two_sports', {}).get(6, 'N/A')}\n\n"
            "**👑 Full Access (All 3 Sports)**\n"
            f"• 1 Month: €{pricing.get('full_access', {}).get(1, 'N/A')}\n"
            f"• 3 Months: €{pricing.get('full_access', {}).get(3, 'N/A')}\n"
            f"• 6 Months: €{pricing.get('full_access', {}).get(6, 'N/A')}\n\n"
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
        pricing_all = get_dynamic_prices()
        pricing = pricing_all.get(plan_type, {})

        price1m = pricing.get(1, 0)
        price3m = pricing.get(3, 0)
        price6m = pricing.get(6, 0)

        keyboard = [
            [InlineKeyboardButton(f"1 Month - €{price1m}", callback_data=f"duration_{plan_type}_1")],
            [InlineKeyboardButton(f"3 Months - €{price3m}", callback_data=f"duration_{plan_type}_3")],
            [InlineKeyboardButton(f"6 Months - €{price6m}", callback_data=f"duration_{plan_type}_6")],
            [InlineKeyboardButton("🔙 Back to Plans", callback_data="view_plans")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            f"**{plan_name}**\n\n"
            "Select your subscription duration:\n\n"
            f"• **1 Month**: €{price1m}\n"
            f"• **3 Months**: €{price3m} (Save €{max(0, (price1m * 3) - price3m):.0f}!)\n"
            f"• **6 Months**: €{price6m} (Save €{max(0, (price1m * 6) - price6m):.0f}!)\n"
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
            # Extract duration (always the last part)
            try:
                duration = int(parts[-1])
            except ValueError:
                logger.error(f"Invalid duration in callback data: {query.data}")
                await query.edit_message_text("❌ Invalid selection. Please try again.")
                return
            
            # Extract plan type (everything between 'duration' and the duration number)
            plan_type_parts = parts[1:-1]  # Skip 'duration' and duration number
            plan_type = '_'.join(plan_type_parts)  # Rejoin with underscores
            
        else:
            logger.error(f"Unexpected callback data format: {query.data}")
            await query.edit_message_text("❌ Invalid selection. Please try again.")
            return
        
        context.user_data['selected_plan_type'] = plan_type
        context.user_data['selected_duration'] = duration
        
        logger.info(f"User selected plan: {plan_type}, duration: {duration}")
        
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
        pricing = get_dynamic_prices()
        price = pricing.get('single_sport', {}).get(duration, 0)
        
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
        elif len(selected) > 0:
            keyboard.append([InlineKeyboardButton(f"⏳ Select {required_count - len(selected)} more sport(s)", callback_data="no_action")])
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"plan_{plan_type}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get pricing and plan names
        pricing = get_dynamic_prices()
        price = pricing.get(plan_type, {}).get(duration, 0)
        
        plan_names = {
            'two_sports': '🔥 2 Combined Sports',
            'full_access': '👑 Full Access (All 3 Sports)'
        }
        plan_name = plan_names.get(plan_type, plan_type.replace('_', ' ').title())
        
        text = (
            f"**{plan_name} - {duration} Month{'s' if duration > 1 else ''}**\n"
            f"**Price**: €{price}\n\n"
            f"Select **{required_count}** sports ({len(selected)}/{required_count} selected):\n"
        )
        
        # Add helpful text
        if len(selected) == 0:
            text += "🔽 Choose your sports below:"
        elif len(selected) < required_count:
            text += f"✅ Great! Select {required_count - len(selected)} more sport(s):"
        else:
            text += "🎉 Perfect! Ready to proceed to payment."
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def handle_sport_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle sport toggle for multi-sport plans"""
        query = update.callback_query
        
        # Handle no_action callback
        if query.data == "no_action":
            await query.answer("Please select the required number of sports to continue", show_alert=True)
            return
            
        await query.answer()
        
        sport = query.data.replace("toggle_sport_", "")
        selected = context.user_data.get('selecting_sports', [])
        plan_type = context.user_data['selected_plan_type']
        
        required_count = 2 if plan_type == 'two_sports' else 3
        
        if sport in selected:
            selected.remove(sport)
            await query.answer(f"❌ Removed {sport.title()}")
        else:
            if len(selected) < required_count:
                selected.append(sport)
                await query.answer(f"✅ Added {sport.title()}")
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
        pricing = get_dynamic_prices()
        price = pricing.get(plan_type, {}).get(duration, 0)
        
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
        """Show user's active subscriptions with real-time data"""
        query = update.callback_query
        await query.answer("📊 Loading your subscriptions...")
        
        user_id = str(update.effective_user.id)
        db = SessionLocal()
        
        try:
            from datetime import datetime, timedelta
            # Use timezone-naive datetime to match database storage
            now = datetime.now(UTC).replace(tzinfo=None)  # Convert to naive datetime for database compatibility
            
            user = db.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                await query.edit_message_text("User not found. Please /start the bot first.")
                return
            
            active_subs = db.query(Subscription).filter_by(
                user_id=user.id,
                is_active=True
            ).filter(Subscription.end_date > now).all()
            
            # Get user activity stats - NotificationLog doesn't have user_id, so we'll skip this for now
            # or get it differently if needed
            recent_notifications = 0  # Placeholder for now
            
            if not active_subs:
                text = f"""📋 **My Subscriptions** *(Updated: {now.strftime("%H:%M")})*

❌ **No Active Subscriptions**

💡 **Why Subscribe?**
• Real-time alerts when favorites trail at halftime
• Premium analytics for Tennis, Basketball & Handball  
• Instant notifications for betting opportunities
• Advanced match insights and statistics

📊 **Your Activity:**
• Notifications (7 days): {recent_notifications}
• Member since: {user.created_at.strftime("%B %Y") if user.created_at else "Unknown"}

🚀 **Join our premium members today!**"""

                keyboard = [
                    [InlineKeyboardButton("💎 View Plans", callback_data="view_plans")],
                    [InlineKeyboardButton("📊 Free Analytics", callback_data="free_analytics")],
                    [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
                except:
                    plain_text = text.replace('*', '').replace('_', '')
                    await query.edit_message_text(plain_text, reply_markup=reply_markup)
            else:
                text = f"🏆 **Your Active Subscriptions** *(Updated: {now.strftime("%H:%M")})*\n\n"
                total_value = 0
                
                for i, sub in enumerate(active_subs, 1):
                    try:
                        # Safely handle sports data
                        if isinstance(sub.sports, list) and sub.sports:
                            sports_text = ", ".join([sport.title() for sport in sub.sports])
                        else:
                            sports_text = "All Sports"
                        
                        # Calculate days remaining - both datetimes are now naive
                        if sub.end_date and isinstance(sub.end_date, datetime):
                            days_left = (sub.end_date - now).days
                        else:
                            days_left = 0  # Fallback if end_date is None or invalid
                        
                        # Status with better indicators
                        if days_left > 14:
                            status = f"🟢 Active ({days_left} days left)"
                        elif days_left > 3:
                            status = f"🟡 Expires in {days_left} days"
                        elif days_left >= 0:
                            status = f"🟠 Expires in {days_left} days! 🚨"
                        else:
                            status = f"🔴 Expired {abs(days_left)} days ago"
                        
                        # Properly format plan names
                        plan_names = {
                            'single_sport': '1 Sport Plan',
                            'two_sports': '2 Combined Sports Plan', 
                            'full_access': 'Full Access Plan'
                        }
                        plan_display = plan_names.get(sub.plan_type, sub.plan_type.replace('_', ' ').title())
                        
                        # Calculate plan value based on plan type and duration
                        pricing = get_dynamic_prices()
                        try:
                            plan_value = pricing.get(sub.plan_type, {}).get(sub.duration_months, 0)
                        except (KeyError, AttributeError):
                            plan_value = 0  # Fallback if pricing not found
                        
                        # Escape Markdown special characters
                        safe_plan = plan_display.replace('*', '\\*').replace('_', '\\_')
                        safe_sports = sports_text.replace('*', '\\*').replace('_', '\\_')
                        
                        # Safe date formatting
                        try:
                            date_str = sub.end_date.strftime('%d/%m/%Y') if sub.end_date else "Unknown"
                        except (AttributeError, ValueError):
                            date_str = "Unknown"
                        
                        text += f"""**{i}\\. {safe_plan}**
📊 Sports: {safe_sports}
{status}
📅 Valid until: {date_str}
💰 Value: €{plan_value:.2f}
⏰ Duration: {sub.duration_months} month(s)

"""
                        total_value += plan_value
                        
                    except Exception as sub_error:
                        logger.error(f"Error processing subscription {sub.id}: {str(sub_error)}")
                        # Skip this subscription and continue with others
                        continue
                
                text += f"""💎 **Total Portfolio Value: €{total_value:.2f}**

🔔 **Activity Summary:**
• Notifications (7 days): {recent_notifications}
• Premium Status: 🟢 Active Member
• Benefits: Real-time alerts, exclusive analytics

💡 **You get instant notifications when favorites trail!**"""
                
                keyboard = [
                    [
                        InlineKeyboardButton("🔄 Extend", callback_data="view_plans"),
                        InlineKeyboardButton("📊 Analytics", callback_data="premium_analytics")
                    ],
                    [
                        InlineKeyboardButton("🔄 Refresh", callback_data="my_subscriptions"),
                        InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
                except Exception as markdown_error:
                    logger.error(f"Markdown parsing error in my_subscriptions: {str(markdown_error)}")
                    # Fallback to plain text if Markdown fails
                    fallback_text = text.replace('*', '').replace('_', '').replace('[', '').replace(']', '').replace('\\', '')
                    await query.edit_message_text(fallback_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in my_subscriptions: {str(e)}")
            # Final fallback message
            try:
                fallback_text = f"🏆 Your Active Subscriptions\n\nThere was an issue displaying your subscriptions. Please try again or contact support.\n\nError: {str(e)[:50]}..."
                keyboard = [[InlineKeyboardButton("📋 View Plans", callback_data="view_plans"), InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]]
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
                target_users = self._get_subscribed_users(db, match.sport)  # Premium notifications to subscribers only
                log_type = 'premium'  # Changed from 'free' since now only paid subscribers get match start notifications
                
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
            
            logger.info(f"📊 Notification summary: {sent_count} sent, {failed_count} failed for {match.sport} match")
            
            # Send admin notification for new match starts
            if notification_type == 'match_start':
                await self.send_admin_match_alert(match, 'new_match_starting', sent_count)
            elif notification_type == 'halftime_trailing':
                await self.send_admin_match_alert(match, 'favorite_trailing', sent_count)
            
            # Mark notification as sent to prevent duplicates
            await odds_tracker.mark_notification_sent(match.id, notification_type)
            
        except Exception as e:
            logger.error(f"❌ Error in send_notification: {str(e)}")
        finally:
            db.close()

    async def send_admin_match_alert(self, match: Match, alert_type: str, user_count: int = 0):
        """Send real-time match alerts to admin"""
        try:
            admin_id = env_config.ADMIN_TELEGRAM_ID
            if not admin_id:
                return
                
            emoji = {'tennis': '🎾', 'basketball': '🏀', 'handball': '🤾'}.get(match.sport, '⚽')
            
            if alert_type == 'new_match_starting':
                text = f"""🚨 **NEW MATCH STARTING** {emoji}

📊 **Match Details:**
• **Sport**: {match.sport.title()}
• **Teams**: {match.home_team} vs {match.away_team}
• **Start Time**: {match.start_time.strftime('%H:%M UTC') if match.start_time else 'Unknown'}
• **Favorite**: {match.home_team if match.pre_match_favorite == 'home' else match.away_team} ({match.pre_match_favorite})

💰 **Pre-match Odds:**
• Home: {match.pre_match_home_odds:.2f} ({match.home_team})
• Away: {match.pre_match_away_odds:.2f} ({match.away_team})"""
                
                if match.sport != 'tennis' and match.pre_match_draw_odds:
                    text += f"\n• Draw: {match.pre_match_draw_odds:.2f}"
                
                text += f"""

📱 **Notification Status:**
• Sent to: {user_count} subscribed users
• Match ID: {match.event_id}
• Time: {datetime.now(UTC).strftime('%H:%M:%S UTC')}

This match is now being monitored for halftime trailing alerts."""

            elif alert_type == 'favorite_trailing':
                text = f"""🚨 **FAVORITE TRAILING ALERT** {emoji}

📊 **Match Details:**
• **Sport**: {match.sport.title()}
• **Teams**: {match.home_team} vs {match.away_team}
• **Favorite**: {match.home_team if match.pre_match_favorite == 'home' else match.away_team}
• **Status**: Trailing at halftime/break

⚠️ **Alert Triggered:**
• Pre-match favorite is now behind
• Betting opportunity detected
• Users notified for potential value

📱 **Notification Status:**
• Sent to: {user_count} subscribed users
• Time: {datetime.now(UTC).strftime('%H:%M:%S UTC')}"""

            elif alert_type == 'match_went_live':
                text = f"""🔴 **MATCH WENT LIVE** {emoji}

📊 **Match Status Update:**
• **Sport**: {match.sport.title()}
• **Teams**: {match.home_team} vs {match.away_team}
• **Status**: Just started (Scheduled → Live)
• **Start Time**: {match.start_time.strftime('%H:%M UTC') if match.start_time else 'Unknown'}

💰 **Tracking Info:**
• **Favorite**: {match.home_team if match.pre_match_favorite == 'home' else match.away_team}
• **Pre-match Odds**: {match.pre_match_home_odds:.2f} - {match.pre_match_away_odds:.2f}"""
                
                if match.sport != 'tennis' and match.pre_match_draw_odds:
                    text += f" - {match.pre_match_draw_odds:.2f}"
                
                text += f"""

🔍 **Monitoring:**
• Match ID: {match.event_id}
• Real-time tracking: Active
• Halftime alerts: Enabled
• Detection time: {datetime.now(UTC).strftime('%H:%M:%S UTC')}

This match is now being monitored for trailing favorite opportunities."""

            # Send to admin
            await self.app.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode='Markdown'
            )
            
            logger.info(f"✅ Admin alert sent: {alert_type} for {match.sport} match")
            
        except Exception as e:
            logger.error(f"❌ Failed to send admin alert: {str(e)}")

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
                Subscription.end_date > datetime.now(UTC),
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
        
        # Calculate time until match starts for display
        from datetime import datetime, UTC
        time_to_start = match.start_time - datetime.now(UTC)
        minutes_to_start = int(time_to_start.total_seconds() / 60)
        
        text = (
            f"{sport_emoji} **MATCH STARTING IN ~{minutes_to_start} MINUTES**\n\n"
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
        """Enhanced notification loop with admin alerts for new match starts"""
        consecutive_errors = 0
        max_consecutive_errors = 5
        notification_check_count = 0
        
        # Track previously seen matches to detect new starts
        previous_live_matches = set()
        
        logger.info("🔔 Starting enhanced notification loop...")
        logger.info("⏰ Checking for notifications every 20 seconds")
        logger.info("📧 Pre-match notifications: 30 minutes before start")
        logger.info("🚨 Halftime notifications: When favorites are trailing")
        logger.info("👨‍💼 Admin alerts: Real-time match start tracking")
        
        while True:
            try:
                notification_check_count += 1
                start_time = datetime.now(UTC)
                
                # Get matches needing notifications
                matches = await odds_tracker.get_matches_for_notification()
                
                match_start_count = len(matches['match_start'])
                halftime_count = len(matches['halftime_trailing'])
                
                # Check for newly started matches (admin tracking)
                db = SessionLocal()
                try:
                    current_live_matches = set()
                    live_matches = db.query(Match).filter(Match.status.in_(['live', 'halftime'])).all()
                    
                    for match in live_matches:
                        current_live_matches.add(match.id)
                        
                        # If this is a new live match (not seen before)
                        if match.id not in previous_live_matches:
                            # Send admin alert for newly started match
                            await self.send_admin_match_alert(match, 'match_went_live', 0)
                            logger.info(f"🔥 NEW LIVE MATCH DETECTED: {match.home_team} vs {match.away_team} ({match.sport})")
                    
                    # Update previous live matches set
                    previous_live_matches = current_live_matches
                    
                finally:
                    db.close()
                
                # Log periodic status with enhanced info
                if notification_check_count % 15 == 1:  # Every 15 checks (5 minutes at 20s intervals)
                    live_count = len(previous_live_matches)
                    logger.info(f"🔔 Notification check #{notification_check_count}: {match_start_count} pre-match, {halftime_count} halftime notifications pending, {live_count} matches currently live")
                
                notifications_sent = 0
                
                # Send match start notifications
                for match in matches['match_start']:
                    time_to_start = match.start_time - datetime.now(UTC)
                    minutes_to_start = int(time_to_start.total_seconds() / 60)
                    logger.info(f"📧 Sending pre-match notification: {match.home_team} vs {match.away_team} ({match.sport}) starts in {minutes_to_start} minutes")
                    await self.send_notification(match, 'match_start')
                    notifications_sent += 1
                
                # Send halftime trailing notifications
                for match in matches['halftime_trailing']:
                    logger.info(f"🚨 Sending halftime trailing notification: {match.home_team} vs {match.away_team} ({match.sport}) - favorite is trailing!")
                    await self.send_notification(match, 'halftime_trailing')
                    notifications_sent += 1
                
                if notifications_sent > 0:
                    logger.info(f"✅ Sent {notifications_sent} notifications in this cycle")
                
                # Reset error counter on successful loop
                consecutive_errors = 0
                
                # Calculate processing time and adjust sleep
                processing_time = (datetime.now(UTC) - start_time).total_seconds()
                sleep_time = max(1, 20 - processing_time)  # Check every 20 seconds, adjusted for processing time
                
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"❌ Error in notification loop (attempt {consecutive_errors}): {str(e)}")
                
                # Handle network errors specifically
                from telegram.error import NetworkError, TimedOut
                if isinstance(e, (NetworkError, TimedOut)) or "httpx" in str(e).lower():
                    logger.warning(f"🌐 Network error in notification loop: {str(e)}")
                    # For network errors, wait longer before retrying
                    await asyncio.sleep(min(60 * consecutive_errors, 300))  # Max 5 minutes
                else:
                    # For other errors, use progressive backoff
                    await asyncio.sleep(min(30 * consecutive_errors, 180))  # Max 3 minutes
                
                # If too many consecutive errors, add extra delay
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(f"🚨 Too many consecutive errors ({consecutive_errors}). Adding extended delay...")
                    await asyncio.sleep(600)  # 10 minutes
                    consecutive_errors = 0  # Reset counter
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Global error handler for the bot"""
        import traceback
        from telegram.error import NetworkError, TimedOut, BadRequest
        
        # Log the error
        logger.error(f"Exception while handling an update: {context.error}")
        
        # Handle specific error types
        if isinstance(context.error, NetworkError):
            logger.warning(f"Network error encountered: {context.error}")
            # For network errors, just log and continue - the bot will retry
            return
            
        elif isinstance(context.error, TimedOut):
            logger.warning(f"Request timed out: {context.error}")
            # For timeouts, just log and continue
            return
            
        elif isinstance(context.error, BadRequest):
            logger.error(f"Bad request error: {context.error}")
            # For bad requests, log the update that caused it
            if update:
                logger.error(f"Update that caused error: {update}")
            return
        
        # For other errors, log with full traceback
        logger.error(f"Full traceback: {''.join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))}")
        
        # Try to notify the user if possible (but don't fail if we can't)
        try:
            if update and hasattr(update, 'effective_chat') and update.effective_chat:
                error_message = "⚠️ Something went wrong. Please try again later."
                if hasattr(update, 'message') and update.message:
                    await update.message.reply_text(error_message)
                elif hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.answer(error_message, show_alert=True)
        except Exception as notify_error:
            logger.error(f"Could not notify user about error: {notify_error}")

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
        """
        Run the bot with optimized polling and robust error handling
        
        Network Error Fixes Implemented:
        ================================
        1. Extended Timeouts: Increased from 10s to 30s for all operations
        2. Connection Pooling: Configured 20 connection pool for better throughput
        3. Robust Error Handling: Added comprehensive error handling for:
           - NetworkError: Logs warning and continues
           - TimedOut: Logs warning and continues  
           - HTTPx ReadError: Retries with 30s delay
           - Other errors: Logs with traceback and retries with backoff
        4. Retry Logic: Automatic restart with progressive delays:
           - Network errors: 30s delay
           - Other errors: 60s delay
           - Multiple retries with exponential backoff
        5. Notification Loop: Enhanced with consecutive error tracking
        6. Global Error Handler: Catches and handles all unhandled exceptions
        
        This configuration makes the bot resilient to:
        - Temporary network outages
        - Telegram API rate limits
        - HTTPx connection issues
        - DNS resolution problems
        - Internet connectivity drops
        """
        # Initialize database
        init_db()
        
        # Create application with robust network configuration
        from telegram.request import HTTPXRequest
        
        # Create custom request handler with proper timeouts
        request = HTTPXRequest(
            connection_pool_size=20,  # Larger connection pool
            read_timeout=30.0,        # 30 second read timeout
            write_timeout=30.0,       # 30 second write timeout
            connect_timeout=30.0,     # 30 second connect timeout
            pool_timeout=30.0,        # 30 second pool timeout
            http_version='1.1'        # Use HTTP/1.1 for better compatibility
        )
        
        application = (
            Application.builder()
            .token(env_config.TELEGRAM_BOT_TOKEN)
            .request(request)
            .post_init(self.post_init)
            .build()
        )
        self.app = application
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("admin", self.admin_panel))
        
        # Callback query handlers
        application.add_handler(CallbackQueryHandler(self.view_plans, pattern="^view_plans$"))
        application.add_handler(CallbackQueryHandler(self.my_subscriptions, pattern="^my_subscriptions$"))
        application.add_handler(CallbackQueryHandler(self.about, pattern="^about$"))
        application.add_handler(CallbackQueryHandler(self.show_duration_selection, pattern="^plan_"))
        application.add_handler(CallbackQueryHandler(self.handle_duration_selection, pattern="^duration_"))
        application.add_handler(CallbackQueryHandler(self.handle_single_sport_selection, pattern="^single_sport_"))
        application.add_handler(CallbackQueryHandler(self.handle_sport_toggle, pattern="^toggle_sport_"))
        application.add_handler(CallbackQueryHandler(self.handle_sport_toggle, pattern="^no_action$"))  # Handle no_action callbacks
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
        application.add_handler(CallbackQueryHandler(self.admin_match_stats, pattern="^admin_match_stats$"))
        application.add_handler(CallbackQueryHandler(self.admin_refresh, pattern="^admin_refresh$"))
        application.add_handler(CallbackQueryHandler(self.admin_force_update, pattern="^admin_force_update$"))
        application.add_handler(CallbackQueryHandler(self.admin_restart, pattern="^admin_restart$"))
        
        # User analytics handlers
        application.add_handler(CallbackQueryHandler(self.free_analytics, pattern="^free_analytics$"))
        application.add_handler(CallbackQueryHandler(self.premium_analytics, pattern="^premium_analytics$"))
        
        # Add global error handler
        application.add_error_handler(self.error_handler)
        
        # Use robust polling with proper error handling
        logger.info("🚀 Starting bot with robust polling and error handling...")
        logger.info("📊 Data fetching runs separately in data_service.py")
        logger.info("🔧 Network configuration: 30s timeouts, 20 connection pool, HTTP/1.1, Robust error handling")
        
        # Start polling with robust configuration
        while True:
            try:
                application.run_polling(
                    allowed_updates=Update.ALL_TYPES, 
                    drop_pending_updates=True,
                    poll_interval=2.0,  # Slightly slower polling for better stability
                    timeout=20,  # Polling timeout for get_updates
                    bootstrap_retries=5,  # Retry on startup failures
                    stop_signals=None  # Handle signals manually for graceful shutdown
                )
                break  # If we get here, the bot stopped normally
                
            except Exception as e:
                logger.error(f"Bot polling error: {str(e)}")
                logger.error(f"Error type: {type(e).__name__}")
                
                # Handle specific network errors
                from telegram.error import NetworkError, TimedOut
                if isinstance(e, (NetworkError, TimedOut)):
                    logger.warning("Network/timeout error detected. Retrying in 30 seconds...")
                    import time
                    time.sleep(30)
                    logger.info("Attempting to restart bot polling...")
                    continue
                elif "httpx.ReadError" in str(e) or "ReadError" in str(e):
                    logger.warning("HTTPx ReadError detected. Retrying in 30 seconds...")
                    import time
                    time.sleep(30)
                    logger.info("Attempting to restart bot polling...")
                    continue
                else:
                    # For other errors, log and retry after a longer delay
                    logger.error(f"Unexpected error: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    logger.warning("Retrying in 60 seconds...")
                    import time
                    time.sleep(60)
                    continue

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin panel for managing the bot"""
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            user_id = str(query.from_user.id)
        else:
            user_id = str(update.effective_user.id)

        if user_id != env_config.ADMIN_TELEGRAM_ID:
            if update.callback_query:
                await update.callback_query.edit_message_text("❌ Access denied.")
            else:
                await update.message.reply_text("❌ Access denied.")
            return

        db = SessionLocal()
        try:
            # Get real-time statistics
            from datetime import datetime, timedelta
            from sqlalchemy import func
            import psutil
            now = datetime.now(UTC)
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Basic stats
            total_users = db.query(User).count()
            new_users_today = db.query(User).filter(User.created_at >= today).count()
            
            active_subs = db.query(Subscription).filter_by(is_active=True).filter(
                Subscription.end_date > now
            ).count()
            
            # Live match data
            live_matches = db.query(Match).filter(Match.status.in_(['live', 'halftime'])).count()
            scheduled_matches = db.query(Match).filter_by(status='scheduled').count()
            trailing_favorites = db.query(Match).filter_by(favorite_trailing_at_halftime=True).count()
            
            # Payment stats
            pending_payments = db.query(Payment).filter_by(status='pending').count()
            completed_today = db.query(Payment).filter(
                Payment.status == 'completed',
                Payment.created_at >= today
            ).count()
            
            # Revenue today
            revenue_today = db.query(Payment).filter(
                Payment.status == 'completed',
                Payment.created_at >= today
            ).with_entities(func.sum(Payment.amount)).scalar() or 0
            
            # Recent notifications (last hour)
            recent_notifications = db.query(NotificationLog).filter(
                NotificationLog.sent_at >= now - timedelta(hours=1)
            ).count()
            
            # System status indicators
            last_notification = db.query(NotificationLog).order_by(
                NotificationLog.sent_at.desc()
            ).first()
            
            last_activity = last_notification.sent_at.strftime("%H:%M") if last_notification else "No activity"
            
            # Check if data service is running
            data_service_status = "❌ Offline"
            try:
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    if proc.info['cmdline'] and 'data_service.py' in ' '.join(proc.info['cmdline']):
                        data_service_status = "✅ Online"
                        break
            except:
                data_service_status = "❓ Unknown"
            
            keyboard = [
                [
                    InlineKeyboardButton("👥 Users", callback_data="admin_users"),
                    InlineKeyboardButton("💳 Payments", callback_data="admin_payments")
                ],
                [
                    InlineKeyboardButton("⚽ Matches", callback_data="admin_matches"),
                    InlineKeyboardButton("🔔 Notifications", callback_data="admin_notifications")
                ],
                [
                    InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
                    InlineKeyboardButton("🔧 System", callback_data="admin_system")
                ],
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh"),
                    InlineKeyboardButton("🧪 Test Data", callback_data="admin_add_test_matches")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Create dynamic status indicators
            user_trend = "📈" if new_users_today > 0 else "➖"
            match_status = "🔴 LIVE" if live_matches > 0 else ("⏰ Scheduled" if scheduled_matches > 0 else "💤 Quiet")
            
            admin_text = f"""
🔧 **Admin Dashboard** *(Updated: {now.strftime("%H:%M")})*

**🎯 Real-Time Overview:**
• Users: {total_users} *({user_trend} +{new_users_today} today)*
• Active Subs: {active_subs}
• Revenue Today: €{revenue_today:.2f} *({completed_today} payments)*

**⚽ Match Status:**
• {match_status} *({live_matches} live, {scheduled_matches} scheduled)*
• Trailing Favorites: {trailing_favorites}

**🔔 Activity:**
• Notifications (1h): {recent_notifications}
• Last Activity: {last_activity}
• Pending Payments: {pending_payments}

**🔧 System Status:**
• Data Service: {data_service_status}

*Select an option for detailed management:*
"""
            
            try:
                if update.callback_query:
                    await query.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
                else:
                    await update.message.reply_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as markdown_error:
                logger.error(f"Markdown parsing error in admin_panel: {str(markdown_error)}")
                # Fallback to plain text if Markdown fails
                fallback_text = admin_text.replace('*', '').replace('_', '').replace('[', '').replace(']', '')
                if update.callback_query:
                    await query.edit_message_text(fallback_text, reply_markup=reply_markup)
                else:
                    await update.message.reply_text(fallback_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in admin_panel: {str(e)}")
            error_msg = f"❌ Error loading admin panel: {str(e)[:100]}..."
            if update.callback_query:
                await query.edit_message_text(error_msg)
            else:
                await update.message.reply_text(error_msg)
        finally:
            db.close()
    
    async def admin_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user management panel with real-time data"""
        query = update.callback_query
        await query.answer("📊 Loading user data...")
        
        db = SessionLocal()
        try:
            from datetime import datetime, timedelta
            now = datetime.now(UTC)
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Get comprehensive user statistics
            total_users = db.query(User).count()
            new_today = db.query(User).filter(User.created_at >= today).count()
            active_subs = db.query(Subscription).filter_by(is_active=True).filter(
                Subscription.end_date > now
            ).count()
            
            # Recent users (last 15)
            users = db.query(User).order_by(User.created_at.desc()).limit(15).all()
            
            def safe_escape(text):
                """Safely escape Markdown special characters"""
                if not text:
                    return "Unknown"
                chars_to_escape = ['*', '_', '`', '[', ']', '(', ')', '#', '+', '-', '.', '!', '\\']
                for char in chars_to_escape:
                    text = text.replace(char, f'\\{char}')
                return text
            
            text = f"""👥 **User Management** *(Updated: {now.strftime("%H:%M")})*

**📊 User Stats:**
• Total Users: {total_users}
• New Today: {new_today}
• Active Subscriptions: {active_subs}
• Conversion Rate: {(active_subs/total_users*100):.1f}% if total_users > 0 else "0%"

**👤 Recent Users (Last 15):**
"""
            
            for i, user in enumerate(users, 1):
                active_sub = db.query(Subscription).filter_by(
                    user_id=user.id, is_active=True
                ).filter(Subscription.end_date > now).first()
                
                status = "🟢 Premium" if active_sub else "🔴 Free"
                safe_first_name = safe_escape(user.first_name or 'Unknown')
                safe_username = safe_escape(user.username or 'no_username')
                
                # Show join date for context
                join_date = user.created_at.strftime("%d/%m") if user.created_at else "Unknown"
                
                text += f"{i}\\. {safe_first_name} (@{safe_username}) \\- {status} \\({join_date}\\)\n"
            
            keyboard = [
                [
                    InlineKeyboardButton("📊 Export Users", callback_data="admin_export_users"),
                    InlineKeyboardButton("🔄 Refresh", callback_data="admin_users")
                ],
                [
                    InlineKeyboardButton("📈 User Stats", callback_data="admin_user_stats"),
                    InlineKeyboardButton("🔙 Back", callback_data="admin_back")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Markdown error in admin_users: {str(e)}")
                # Fallback to plain text if Markdown fails
                plain_text = text.replace('*', '').replace('_', '').replace('\\', '').replace('[', '').replace(']', '')
                await query.edit_message_text(plain_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in admin_users: {str(e)}")
            await query.edit_message_text(f"❌ Error loading users: {str(e)[:100]}...")
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
        """Enhanced match management panel with detailed odds and real-time tracking"""
        query = update.callback_query
        await query.answer("📊 Loading detailed match data...")
        
        db = SessionLocal()
        try:
            from datetime import datetime, timedelta
            now = datetime.now(UTC)
            
            # Get matches by status for comprehensive overview
            live_matches = db.query(Match).filter(Match.status.in_(['live', 'halftime'])).order_by(Match.updated_at.desc()).all()
            scheduled_matches = db.query(Match).filter_by(status='scheduled').order_by(Match.start_time.asc()).limit(10).all()
            
            # Get recently started matches (last 30 minutes)
            recent_start_cutoff = now - timedelta(minutes=30)
            recently_started = db.query(Match).filter(
                Match.status.in_(['live', 'halftime']),
                Match.updated_at >= recent_start_cutoff
            ).order_by(Match.updated_at.desc()).all()
            
            # Get matches starting soon (next 60 minutes)
            upcoming_cutoff = now + timedelta(minutes=60)
            starting_soon = db.query(Match).filter(
                Match.status == 'scheduled',
                Match.start_time <= upcoming_cutoff,
                Match.start_time >= now
            ).order_by(Match.start_time.asc()).all()
            
            # Get trailing favorites with recent activity
            trailing_matches = db.query(Match).filter_by(
                favorite_trailing_at_halftime=True
            ).order_by(Match.updated_at.desc()).limit(8).all()
            
            def format_match_with_odds(match):
                """Enhanced match formatting with odds and detailed info"""
                emoji = {'tennis': '🎾', 'basketball': '🏀', 'handball': '🤾'}.get(match.sport, '⚽')
                safe_home = (match.home_team or "Unknown").replace('*', '\\*').replace('_', '\\_')
                safe_away = (match.away_team or "Unknown").replace('*', '\\*').replace('_', '\\_')
                
                # Status indicators with more detail
                status_indicators = {
                    'live': '🔴 LIVE',
                    'halftime': '⏸️ HALF',
                    'scheduled': '⏰ SCHED',
                    'finished': '✅ FIN',
                    'cancelled': '❌ CANC'
                }
                status = status_indicators.get(match.status, f'❓ {match.status.upper()}')
                
                # Odds display
                odds_text = ""
                if match.pre_match_home_odds and match.pre_match_away_odds:
                    home_odds = f"{match.pre_match_home_odds:.2f}"
                    away_odds = f"{match.pre_match_away_odds:.2f}"
                    
                    if match.sport != 'tennis' and match.pre_match_draw_odds:
                        draw_odds = f"{match.pre_match_draw_odds:.2f}"
                        odds_text = f" | Odds: {home_odds} - {draw_odds} - {away_odds}"
                    else:
                        odds_text = f" | Odds: {home_odds} - {away_odds}"
                
                # Favorite indicator
                fav_indicator = ""
                if match.pre_match_favorite:
                    fav_team = safe_home if match.pre_match_favorite == 'home' else safe_away
                    fav_indicator = f" | Fav: {fav_team}"
                    
                    # Add trailing indicator
                    if match.favorite_trailing_at_halftime:
                        fav_indicator += " 🚨"
                
                # Time info
                time_info = ""
                if match.start_time:
                    if match.status == 'scheduled':
                        time_diff = match.start_time - now
                        if time_diff.total_seconds() > 0:
                            minutes_to_start = int(time_diff.total_seconds() / 60)
                            if minutes_to_start < 60:
                                time_info = f" | In {minutes_to_start}m"
                            else:
                                time_info = f" | {match.start_time.strftime('%H:%M')}"
                        else:
                            time_info = " | Should be live"
                    elif match.status in ['live', 'halftime']:
                        time_info = f" | Since {match.start_time.strftime('%H:%M')}"
                
                # Current score if available
                score_info = ""
                if hasattr(match, 'current_score') and match.current_score:
                    if isinstance(match.current_score, dict):
                        home_score = match.current_score.get('home', 0)
                        away_score = match.current_score.get('away', 0)
                        score_info = f" | Score: {home_score}-{away_score}"
                
                return (f"• {emoji} **{safe_home}** vs **{safe_away}** {status}"
                       f"{time_info}{odds_text}{fav_indicator}{score_info}")
            
            # Build the comprehensive admin message
            text = "⚽ **Advanced Match Control Center** 📊\n\n"
            
            # Recently Started Matches (New Feature)
            if recently_started:
                text += "🔥 **Just Started (Last 30min):**\n"
                for match in recently_started:
                    elapsed = now - match.updated_at
                    minutes_ago = int(elapsed.total_seconds() / 60)
                    text += format_match_with_odds(match) + f" ({minutes_ago}m ago)\n"
                text += "\n"
            
            # Starting Soon
            if starting_soon:
                text += "⏰ **Starting Soon (Next 60min):**\n"
                for match in starting_soon:
                    text += format_match_with_odds(match) + "\n"
                text += "\n"
            
            # Currently Live Matches
            if live_matches:
                text += "🔴 **Live Matches:**\n"
                for match in live_matches:
                    text += format_match_with_odds(match) + "\n"
                text += "\n"
            
            # Scheduled Matches (Next 10)
            if scheduled_matches:
                text += "📅 **Upcoming Matches:**\n"
                for match in scheduled_matches[:5]:  # Show top 5 to avoid message length
                    text += format_match_with_odds(match) + "\n"
                if len(scheduled_matches) > 5:
                    text += f"... and {len(scheduled_matches) - 5} more scheduled\n"
                text += "\n"
            
            # Trailing Favorites Alert
            if trailing_matches:
                text += "🚨 **Trailing Favorites Alert:**\n"
                for match in trailing_matches:
                    text += format_match_with_odds(match) + "\n"
                text += "\n"
            
            # Comprehensive Statistics
            total_matches = db.query(Match).count()
            matches_by_sport = {
                'tennis': db.query(Match).filter_by(sport='tennis').count(),
                'basketball': db.query(Match).filter_by(sport='basketball').count(),
                'handball': db.query(Match).filter_by(sport='handball').count()
            }
            
            # Live statistics by sport
            live_by_sport = {
                'tennis': db.query(Match).filter_by(sport='tennis', status='live').count(),
                'basketball': db.query(Match).filter_by(sport='basketball', status='live').count(),
                'handball': db.query(Match).filter_by(sport='handball', status='live').count()
            }
            
            # Get data freshness info
            latest_match = db.query(Match).order_by(Match.updated_at.desc()).first()
            last_data_update = latest_match.updated_at.strftime("%H:%M:%S") if latest_match else "Never"
            
            # Check real-time data service status
            import psutil
            data_service_running = False
            try:
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    if proc.info['cmdline'] and 'data_service.py' in ' '.join(proc.info['cmdline']):
                        data_service_running = True
                        break
            except:
                pass
            
            # Recent API activity (last 5 minutes)
            recent_api_cutoff = now - timedelta(minutes=5)
            recent_updates = db.query(Match).filter(Match.updated_at >= recent_api_cutoff).count()
            
            text += "📊 **Real-Time Statistics:**\n"
            text += f"• **Total Database**: {total_matches} matches\n"
            text += f"• **Currently Live**: {len(live_matches)} ({live_by_sport['tennis']}🎾 {live_by_sport['basketball']}🏀 {live_by_sport['handball']}🤾)\n"
            text += f"• **Scheduled**: {len(scheduled_matches)} upcoming\n"
            text += f"• **Trailing Favs**: {len(trailing_matches)} active\n"
            text += f"• **Recent API Updates**: {recent_updates} (5min)\n\n"
            
            text += "🔧 **System Status:**\n"
            data_status = "🟢 Active" if data_service_running else "🔴 Offline"
            text += f"• **Data Service**: {data_status}\n"
            text += f"• **Last Update**: {last_data_update}\n"
            text += f"• **Real-time Mode**: {'ON' if data_service_running else 'OFF'}\n\n"
            
            # Sport breakdown
            text += "🏆 **Sport Distribution:**\n"
            text += f"• 🎾 Tennis: {matches_by_sport['tennis']} total ({live_by_sport['tennis']} live)\n"
            text += f"• 🏀 Basketball: {matches_by_sport['basketball']} total ({live_by_sport['basketball']} live)\n"
            text += f"• 🤾 Handball: {matches_by_sport['handball']} total ({live_by_sport['handball']} live)\n"
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Refresh Data", callback_data="admin_matches"),
                    InlineKeyboardButton("⚡ Force Update", callback_data="admin_force_update")
                ],
                [
                    InlineKeyboardButton("📈 Match Stats", callback_data="admin_match_stats"),
                    InlineKeyboardButton("🔔 Notifications", callback_data="admin_notifications")
                ],
                [
                    InlineKeyboardButton("🧪 Test Matches", callback_data="admin_add_test_matches"),
                    InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as markdown_error:
                logger.error(f"Markdown parsing error in admin_matches: {str(markdown_error)}")
                # Fallback to plain text
                fallback_text = text.replace('*', '').replace('_', '').replace('[', '').replace(']', '').replace('\\', '')
                await query.edit_message_text(fallback_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in admin_matches: {str(e)}")
            await query.edit_message_text(
                f"❌ **Error Loading Match Data**\n\n"
                f"Error: {str(e)[:100]}...\n\n"
                "This might be due to:\n"
                "• Database connection issues\n"
                "• High data volume\n"
                "• API synchronization problems\n\n"
                "Try refreshing or check system status.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Try Again", callback_data="admin_matches")],
                    [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
                ])
            )
        finally:
            db.close()

    async def admin_force_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Force manual update of match data from APIs"""
        query = update.callback_query
        await query.answer("🔄 Fetching latest match data...")
        
        user_id = str(query.from_user.id)
        if user_id != env_config.ADMIN_TELEGRAM_ID:
            await query.edit_message_text("❌ Access denied.")
            return
        
        try:
            # Show loading message
            await query.edit_message_text(
                "🔄 **Fetching Real-Time Data...**\n\n"
                "• Connecting to sports APIs\n"
                "• Updating match data\n"
                "• Processing odds\n\n"
                "Please wait..."
            )
            
            # Trigger manual odds update
            await odds_tracker.fetch_and_update_matches()
            
            # Get fresh statistics after update
            db = SessionLocal()
            try:
                total_matches = db.query(Match).count()
                live_matches = db.query(Match).filter(Match.status.in_(['live', 'halftime'])).count()
                scheduled_matches = db.query(Match).filter_by(status='scheduled').count()
                trailing_favorites = db.query(Match).filter_by(favorite_trailing_at_halftime=True).count()
                
                # Get recent updates (last 5 minutes)
                from datetime import datetime, timedelta
                recent_cutoff = datetime.now(UTC) - timedelta(minutes=5)
                recent_updates = db.query(Match).filter(Match.updated_at >= recent_cutoff).count()
                
                text = f"✅ **Real-Time Update Complete**\n\n"
                text += f"📊 **Current Status:**\n"
                text += f"• Total Matches: {total_matches}\n"
                text += f"• Live: {live_matches}\n"
                text += f"• Scheduled: {scheduled_matches}\n"
                text += f"• Trailing Favorites: {trailing_favorites}\n"
                text += f"• Recently Updated: {recent_updates}\n\n"
                text += f"*Last Update: {datetime.now(UTC).strftime('%H:%M:%S UTC')}*\n\n"
                text += "Data is now synchronized with live sports APIs!"
                
                keyboard = [
                    [InlineKeyboardButton("⚽ View Updated Matches", callback_data="admin_matches")],
                    [InlineKeyboardButton("🔄 Update Again", callback_data="admin_force_update")],
                    [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error in force update: {str(e)}")
            await query.edit_message_text(
                f"❌ **Update Failed**\n\n"
                f"Error: {str(e)}\n\n"
                "This might be due to:\n"
                "• API connection issues\n"
                "• Network problems\n"
                "• Invalid API credentials\n\n"
                "Check logs for more details.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Try Again", callback_data="admin_force_update")],
                    [InlineKeyboardButton("🔙 Back to Matches", callback_data="admin_matches")]
                ])
            )
    
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
        
        # Try to get system info with psutil, fallback if not available
        try:
            import psutil
            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            system_resources = f"""**System Resources:**
• CPU Usage: {cpu_percent}%
• Memory: {memory.percent}% ({memory.used // (1024**3):.1f}GB / {memory.total // (1024**3):.1f}GB)
• Disk: {disk.percent}% ({disk.used // (1024**3):.1f}GB / {disk.total // (1024**3):.1f}GB)"""
        except ImportError:
            system_resources = """**System Resources:**
• CPU Usage: ❓ (psutil not available)
• Memory: ❓ (psutil not available)  
• Disk: ❓ (psutil not available)"""
        except Exception as e:
            system_resources = f"""**System Resources:**
• Error getting system info: {str(e)[:50]}..."""
        
        # Check if ngrok is running
        ngrok_status = "🟢 Running" if os.path.exists('/tmp/ngrok.pid') else "🔴 Not detected"
        
        # Database status
        db = SessionLocal()
        try:
            db.execute("SELECT 1")
            db_status = "🟢 Connected"
        except Exception as e:
            db_status = f"🔴 Error: {str(e)[:30]}..."
        finally:
            db.close()
        
        text = f"""
🔧 **System Status**

{system_resources}

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
        
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Markdown error in admin_system_status: {str(e)}")
            # Fallback to plain text if Markdown fails
            plain_text = text.replace('*', '').replace('_', '').replace('\\', '').replace('[', '').replace(']', '')
            await query.edit_message_text(plain_text, reply_markup=reply_markup)
    
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
        """Return to main admin panel with real-time data"""
        query = update.callback_query
        await query.answer("🔄 Refreshing admin panel...")
        
        user_id = str(query.from_user.id)
        
        if user_id != env_config.ADMIN_TELEGRAM_ID:
            await query.edit_message_text("❌ Access denied.")
            return
        
        await self._refresh_admin_panel(query)

    async def admin_refresh(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Refresh admin panel with latest data"""
        query = update.callback_query
        await query.answer("🔄 Refreshing data...")
        await self._refresh_admin_panel(query)

    async def _refresh_admin_panel(self, query):
        """Helper function to refresh admin panel data"""
        db = SessionLocal()
        try:
            # Get real-time statistics (same as admin_panel)
            from datetime import datetime, timedelta
            from sqlalchemy import func
            import psutil
            now = datetime.now(UTC)
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Basic stats
            total_users = db.query(User).count()
            new_users_today = db.query(User).filter(User.created_at >= today).count()
            
            active_subs = db.query(Subscription).filter_by(is_active=True).filter(
                Subscription.end_date > now
            ).count()
            
            # Live match data
            live_matches = db.query(Match).filter(Match.status.in_(['live', 'halftime'])).count()
            scheduled_matches = db.query(Match).filter_by(status='scheduled').count()
            trailing_favorites = db.query(Match).filter_by(favorite_trailing_at_halftime=True).count()
            
            # Payment stats
            pending_payments = db.query(Payment).filter_by(status='pending').count()
            completed_today = db.query(Payment).filter(
                Payment.status == 'completed',
                Payment.created_at >= today
            ).count()
            
            # Revenue today
            revenue_today = db.query(Payment).filter(
                Payment.status == 'completed',
                Payment.created_at >= today
            ).with_entities(func.sum(Payment.amount)).scalar() or 0
            
            # Recent notifications (last hour)
            recent_notifications = db.query(NotificationLog).filter(
                NotificationLog.sent_at >= now - timedelta(hours=1)
            ).count()
            
            # System status indicators
            last_notification = db.query(NotificationLog).order_by(
                NotificationLog.sent_at.desc()
            ).first()
            
            last_activity = last_notification.sent_at.strftime("%H:%M") if last_notification else "No activity"
            
            # Check if data service is running
            data_service_status = "❌ Offline"
            try:
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    if proc.info['cmdline'] and 'data_service.py' in ' '.join(proc.info['cmdline']):
                        data_service_status = "✅ Online"
                        break
            except:
                data_service_status = "❓ Unknown"

            
            keyboard = [
                [
                    InlineKeyboardButton("👥 Users", callback_data="admin_users"),
                    InlineKeyboardButton("💳 Payments", callback_data="admin_payments")
                ],
                [
                    InlineKeyboardButton("⚽ Matches", callback_data="admin_matches"),
                    InlineKeyboardButton("🔔 Notifications", callback_data="admin_notifications")
                ],
                [
                    InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
                    InlineKeyboardButton("🔧 System", callback_data="admin_system")
                ],
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh"),
                    InlineKeyboardButton("🧪 Test Data", callback_data="admin_add_test_matches")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Create dynamic status indicators
            user_trend = "📈" if new_users_today > 0 else "➖"
            match_status = "🔴 LIVE" if live_matches > 0 else ("⏰ Scheduled" if scheduled_matches > 0 else "💤 Quiet")
            
            admin_text = f"""
🔧 **Admin Dashboard** *(Updated: {now.strftime("%H:%M")})*

**🎯 Real-Time Overview:**
• Users: {total_users} *({user_trend} +{new_users_today} today)*
• Active Subs: {active_subs}
• Revenue Today: €{revenue_today:.2f} *({completed_today} payments)*

**⚽ Match Status:**
• {match_status} *({live_matches} live, {scheduled_matches} scheduled)*
• Trailing Favorites: {trailing_favorites}

**🔔 Activity:**
• Notifications (1h): {recent_notifications}
• Last Activity: {last_activity}
• Pending Payments: {pending_payments}

**🔧 System Status:**
• Data Service: {data_service_status}

*Select an option for detailed management:*
"""
            
            try:
                await query.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as markdown_error:
                logger.error(f"Markdown parsing error in admin refresh: {str(markdown_error)}")
                # Fallback to plain text if Markdown fails
                fallback_text = admin_text.replace('*', '').replace('_', '').replace('[', '').replace(']', '')
                await query.edit_message_text(fallback_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error refreshing admin panel: {str(e)}")
            await query.edit_message_text(f"❌ Error refreshing: {str(e)[:100]}...")
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
                            start_time=datetime.now(UTC) + timedelta(hours=2),
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
            from sqlalchemy import func
            total_revenue = db.query(Payment).filter_by(status='completed').with_entities(
                func.sum(Payment.amount)
            ).scalar() or 0
            
            pending_revenue = db.query(Payment).filter_by(status='pending').with_entities(
                func.sum(Payment.amount)
            ).scalar() or 0
            
            # Revenue by plan type
            revenue_by_plan = db.query(Payment.plan_type, func.sum(Payment.amount)).filter_by(
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
            from sqlalchemy import func
            total_notifications = db.query(NotificationLog).count()
            successful_notifications = db.query(NotificationLog).filter_by(success=True).count()
            failed_notifications = db.query(NotificationLog).filter_by(success=False).count()
            
            # Notifications by type
            notifications_by_type = db.query(
                NotificationLog.notification_type,
                func.count(NotificationLog.id)
            ).group_by(NotificationLog.notification_type).all()
            
            # Notifications by channel type
            notifications_by_channel = db.query(
                NotificationLog.channel_type,
                func.count(NotificationLog.id)
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
            from sqlalchemy import func
            total_users = db.query(User).count()
            active_users = db.query(User).filter_by(is_active=True).count()
            
            # Subscription statistics
            total_subs = db.query(Subscription).count()
            active_subs = db.query(Subscription).filter_by(is_active=True).filter(
                Subscription.end_date > datetime.now(UTC)
            ).count()
            expired_subs = db.query(Subscription).filter(
                Subscription.end_date <= datetime.now(UTC)
            ).count()
            
            # Subscription by plan type
            subs_by_plan = db.query(
                Subscription.plan_type,
                func.count(Subscription.id)
            ).filter_by(is_active=True).filter(
                Subscription.end_date > datetime.now(UTC)
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
                func.sum(Payment.amount)
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

    async def admin_match_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed match statistics and analytics"""
        query = update.callback_query
        await query.answer("📊 Loading detailed match stats...")
        
        db = SessionLocal()
        try:
            from sqlalchemy import func
            from datetime import datetime, timedelta
            now = datetime.now(UTC)
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Overall match statistics
            total_matches = db.query(Match).count()
            live_matches = db.query(Match).filter(Match.status.in_(['live', 'halftime'])).count()
            scheduled_matches = db.query(Match).filter_by(status='scheduled').count()
            finished_matches = db.query(Match).filter_by(status='finished').count()
            
            # Matches by sport
            matches_by_sport = db.query(
                Match.sport,
                func.count(Match.id)
            ).group_by(Match.sport).all()
            
            # Trailing favorites statistics
            total_trailing = db.query(Match).filter_by(favorite_trailing_at_halftime=True).count()
            trailing_by_sport = db.query(
                Match.sport,
                func.count(Match.id)
            ).filter_by(favorite_trailing_at_halftime=True).group_by(Match.sport).all()
            
            # Recent activity (last 24 hours)
            recent_matches = db.query(Match).filter(
                Match.updated_at >= today
            ).count()
            
            # Live matches detail
            current_live = db.query(Match).filter(
                Match.status.in_(['live', 'halftime'])
            ).order_by(Match.updated_at.desc()).limit(10).all()
            
            # Recent trailing favorites
            recent_trailing = db.query(Match).filter_by(
                favorite_trailing_at_halftime=True
            ).order_by(Match.updated_at.desc()).limit(5).all()
            
            # Odds analysis
            avg_home_odds = db.query(func.avg(Match.pre_match_home_odds)).scalar() or 0
            avg_away_odds = db.query(func.avg(Match.pre_match_away_odds)).scalar() or 0
            
            # Favorites distribution
            home_favorites = db.query(Match).filter_by(pre_match_favorite='home').count()
            away_favorites = db.query(Match).filter_by(pre_match_favorite='away').count()
            
            text = f"📊 **Detailed Match Statistics**\n\n"
            
            text += f"**📈 Overview**:\n"
            text += f"• Total Matches: {total_matches}\n"
            text += f"• Live/Halftime: {live_matches}\n"
            text += f"• Scheduled: {scheduled_matches}\n"
            text += f"• Finished: {finished_matches}\n"
            text += f"• Updated Today: {recent_matches}\n\n"
            
            text += f"**🏆 By Sport**:\n"
            for sport, count in matches_by_sport:
                sport_emoji = {'tennis': '🎾', 'basketball': '🏀', 'handball': '🤾'}.get(sport, '⚽')
                text += f"• {sport_emoji} {sport.title()}: {count}\n"
            
            text += f"\n**📊 Odds Analysis**:\n"
            text += f"• Avg Home Odds: {avg_home_odds:.2f}\n"
            text += f"• Avg Away Odds: {avg_away_odds:.2f}\n"
            text += f"• Home Favorites: {home_favorites}\n"
            text += f"• Away Favorites: {away_favorites}\n"
            
            text += f"\n**🚨 Trailing Favorites**:\n"
            text += f"• Total: {total_trailing}\n"
            for sport, count in trailing_by_sport:
                sport_emoji = {'tennis': '🎾', 'basketball': '🏀', 'handball': '🤾'}.get(sport, '⚽')
                text += f"• {sport_emoji} {sport.title()}: {count}\n"
            
            if current_live:
                text += f"\n**🔴 Current Live Matches** (Top 5):\n"
                for match in current_live[:5]:
                    sport_emoji = {'tennis': '🎾', 'basketball': '🏀', 'handball': '🤾'}.get(match.sport, '⚽')
                    status_emoji = {'live': '🔴', 'halftime': '⏸️'}.get(match.status, '❓')
                    safe_home = match.home_team.replace('*', '\\*').replace('_', '\\_') if match.home_team else "Unknown"
                    safe_away = match.away_team.replace('*', '\\*').replace('_', '\\_') if match.away_team else "Unknown"
                    score = f"{match.current_score_home}-{match.current_score_away}" if match.current_score_home is not None else "0-0"
                    text += f"• {sport_emoji} {safe_home} vs {safe_away} {status_emoji} ({score})\n"
            
            if recent_trailing:
                text += f"\n**⚠️ Recent Trailing Favorites**:\n"
                for match in recent_trailing[:3]:
                    sport_emoji = {'tennis': '🎾', 'basketball': '🏀', 'handball': '🤾'}.get(match.sport, '⚽')
                    safe_home = match.home_team.replace('*', '\\*').replace('_', '\\_') if match.home_team else "Unknown"
                    safe_away = match.away_team.replace('*', '\\*').replace('_', '\\_') if match.away_team else "Unknown"
                    favorite_team = safe_home if match.pre_match_favorite == 'home' else safe_away
                    text += f"• {sport_emoji} {favorite_team} (favorite) trailing\n"
            
            # Calculate efficiency metrics
            total_notifications_sent = db.query(NotificationLog).count()
            match_related_notifications = db.query(NotificationLog).filter(
                NotificationLog.notification_type.in_(['match_start', 'halftime_trailing'])
            ).count()
            
            text += f"\n**🔔 Notification Efficiency**:\n"
            text += f"• Match Notifications: {match_related_notifications}\n"
            text += f"• Total Notifications: {total_notifications_sent}\n"
            if total_notifications_sent > 0:
                efficiency = (match_related_notifications / total_notifications_sent) * 100
                text += f"• Match Notification %: {efficiency:.1f}%\n"
            
            text += f"\n*Last updated: {now.strftime('%H:%M:%S')}*"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin_match_stats")],
                [InlineKeyboardButton("📊 Export Match Data", callback_data="admin_export_matches")],
                [InlineKeyboardButton("🔙 Back to Matches", callback_data="admin_matches")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Markdown error in admin_match_stats: {str(e)}")
                # Fallback to plain text
                plain_text = text.replace('*', '').replace('_', '').replace('\\', '')
                await query.edit_message_text(plain_text, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in admin_match_stats: {str(e)}")
            # Simple fallback message
            error_text = f"📊 **Match Statistics**\n\nError loading detailed statistics: {str(e)}\n\nPlease try again or check the logs for more details."
            keyboard = [
                [InlineKeyboardButton("🔙 Back to Matches", callback_data="admin_matches")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(error_text, reply_markup=reply_markup)
        finally:
            db.close()

    async def admin_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin restart services request"""
        query = update.callback_query
        await query.answer("🔄 Restart functionality is not implemented yet. This would restart system services.")
        
        # For now, just show a message and go back to system status
        await query.edit_message_text(
            "🔄 **Service Restart**\n\n"
            "⚠️ **Note**: Automatic service restart is not yet implemented.\n\n"
            "**Manual restart options:**\n"
            "• Restart the bot: `sudo systemctl restart telegram-bot`\n"
            "• Restart data service: `sudo systemctl restart data-service`\n"
            "• Restart webhook: `sudo systemctl restart webhook-server`\n\n"
            "Contact the system administrator for manual restarts.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to System", callback_data="admin_system")]
            ])
        )

    async def free_analytics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show free analytics for non-subscribers"""
        query = update.callback_query
        await query.answer("📊 Loading free analytics...")
        
        user_id = str(update.effective_user.id)
        db = SessionLocal()
        
        try:
            from datetime import datetime, timedelta
            now = datetime.now(UTC)
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Basic free analytics
            total_matches_today = db.query(Match).filter(
                Match.created_at >= today
            ).count()
            
            live_matches = db.query(Match).filter(
                Match.status.in_(['live', 'halftime'])
            ).count()
            
            scheduled_matches = db.query(Match).filter_by(status='scheduled').count()
            
            # Free tier limitations message
            text = f"""📊 **Free Analytics** *(Updated: {now.strftime("%H:%M")})*

**📈 Basic Match Stats:**
• Matches today: {total_matches_today}
• Currently live: {live_matches}
• Scheduled: {scheduled_matches}

**💡 Upgrade for Premium Analytics:**
• Detailed match statistics
• Historical data analysis
• Win/loss patterns
• Odds movement tracking
• Custom notifications
• Advanced filtering

🔒 **Premium features require an active subscription.**
"""
            
            keyboard = [
                [InlineKeyboardButton("💎 View Plans", callback_data="view_plans")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in free_analytics: {str(e)}")
            await query.edit_message_text(
                "❌ Error loading analytics. Please try again later.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
                ])
            )
        finally:
            db.close()

    async def premium_analytics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show premium analytics for subscribers"""
        query = update.callback_query
        await query.answer("📊 Loading premium analytics...")
        
        user_id = str(update.effective_user.id)
        db = SessionLocal()
        
        try:
            from datetime import datetime, timedelta
            from sqlalchemy import func
            now = datetime.now(UTC)
            
            # Check if user has active subscription
            user = db.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                await query.edit_message_text("User not found. Please /start the bot first.")
                return
            
            active_subs = db.query(Subscription).filter_by(
                user_id=user.id,
                is_active=True
            ).filter(Subscription.end_date > now).all()
            
            if not active_subs:
                await query.edit_message_text(
                    "🔒 **Premium Analytics**\n\n"
                    "❌ You need an active subscription to access premium analytics.\n\n"
                    "Subscribe to unlock:\n"
                    "• Detailed match statistics\n"
                    "• Historical data analysis\n"
                    "• Win/loss patterns\n"
                    "• Odds movement tracking",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💎 View Plans", callback_data="view_plans")],
                        [InlineKeyboardButton("🔙 Back", callback_data="my_subscriptions")]
                    ])
                )
                return
            
            # Get advanced analytics for subscribers
            week_ago = now - timedelta(days=7)
            month_ago = now - timedelta(days=30)
            
            # Notification stats
            weekly_notifications = db.query(NotificationLog).filter(
                NotificationLog.sent_at >= week_ago
            ).count()
            
            monthly_notifications = db.query(NotificationLog).filter(
                NotificationLog.sent_at >= month_ago
            ).count()
            
            # Match stats by sport
            sports_stats = []
            user_sports = []
            for sub in active_subs:
                if sub.plan_type == 'full_access':
                    user_sports = ['tennis', 'basketball', 'handball']
                    break
                elif sub.sports:
                    user_sports.extend(sub.sports)
            
            for sport in set(user_sports):
                sport_matches = db.query(Match).filter_by(sport=sport).filter(
                    Match.created_at >= week_ago
                ).count()
                
                sport_live = db.query(Match).filter(
                    Match.sport == sport,
                    Match.status.in_(['live', 'halftime'])
                ).count()
                
                sports_stats.append(f"• {sport.capitalize()}: {sport_matches} this week ({sport_live} live)")
            
            sports_text = "\n".join(sports_stats) if sports_stats else "• No sport data available"
            
            text = f"""📊 **Premium Analytics** *(Updated: {now.strftime("%H:%M")})*

**🎯 Your Subscription Coverage:**
{sports_text}

**📈 Notification Activity:**
• This week: {weekly_notifications} notifications
• This month: {monthly_notifications} notifications

**🔔 Recent Performance:**
• Match start alerts: Active
• Halftime alerts: Active for trailing favorites
• Custom filtering: Based on your sports

**⚡ Real-time Features:**
• Live odds tracking: ✅ Active
• Match status updates: ✅ Active
• Premium notifications: ✅ Active

💡 Analytics update every 30 seconds with live data.
"""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="premium_analytics")],
                [InlineKeyboardButton("🔙 Back", callback_data="my_subscriptions")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in premium_analytics: {str(e)}")
            await query.edit_message_text(
                "❌ Error loading analytics. Please try again later.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="my_subscriptions")]
                ])
            )
        finally:
            db.close()

    async def about(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show information about the bot"""
        query = update.callback_query
        await query.answer()
        
        about_text = (
            "🎯 **Premium Betting Analytics Bot**\n\n"
            "**What we do:**\n"
            "• 📊 Real-time odds monitoring for Tennis, Basketball & Handball\n"
            "• 🚨 Instant notifications when favorites are trailing\n"
            "• 🎾 Tennis: Alerts after first set completion\n"
            "• 🏀 Basketball: Alerts at halftime (after 2nd quarter)\n"
            "• 🤾 Handball: Alerts at halftime (30 minutes)\n\n"
            "**Features:**\n"
            "• ⚡ Real-time match tracking\n"
            "• 📱 Instant Telegram notifications\n"
            "• 🎯 Smart favorite detection\n"
            "• 📈 Pre-match odds analysis\n"
            "• 🔔 Timely alerts 30 minutes before matches\n\n"
            "**Subscription Plans:**\n"
            "• 🏆 Single Sport: Focus on one sport\n"
            "• 🔥 Two Sports: Combine any two sports\n"
            "• 👑 Full Access: All three sports\n\n"
            "💡 **Perfect for finding value bets when favorites are struggling!**"
        )
        
        keyboard = [
            [InlineKeyboardButton("📋 View Plans", callback_data="view_plans")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(about_text, reply_markup=reply_markup, parse_mode='Markdown')

if __name__ == "__main__":
    bot = BettingBot()
    bot.run()
