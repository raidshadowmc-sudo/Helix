from flask import jsonify, request, session, flash, redirect, url_for
from app import app, db
from models import Player, PlayerBadge, Badge

@app.route('/api/leaderboard')
def api_leaderboard():
    """API endpoint for leaderboard data with fallback"""
    try:
        sort_by = request.args.get('sort', 'experience')
        limit = min(int(request.args.get('limit', 50)), 100)

        players = Player.get_leaderboard(sort_by=sort_by, limit=limit) or []

        # Convert players to dict format
        players_data = []
        for player in players:
            players_data.append({
                'id': player.id,
                'nickname': player.nickname,
                'level': player.level,
                'experience': player.experience,
                'kills': player.kills,
                'deaths': player.deaths,
                'wins': player.wins,
                'games_played': player.games_played,
                'kd_ratio': player.kd_ratio,
                'win_rate': player.win_rate
            })

        return jsonify({
            'success': True,
            'players': players_data,
            'total': len(players_data)
        })
    except Exception as e:
        app.logger.error(f"Error in API leaderboard: {e}")
        return jsonify({
            'success': False,
            'players': [],
            'total': 0,
            'error': 'Failed to load leaderboard data'
        }), 200  # Still return 200 with empty data

@app.route('/api/stats')
def api_stats():
    """API endpoint for statistics data"""
    try:
        stats = Player.get_statistics()
        # Convert Player objects to dictionaries
        serializable_stats = {}
        for key, value in stats.items():
            if hasattr(value, '__dict__'):  # If it's a model instance
                if hasattr(value, 'nickname'):  # Player object
                    serializable_stats[key] = {
                        'id': value.id,
                        'nickname': value.nickname,
                        'level': value.level,
                        'experience': value.experience,
                        'coins': getattr(value, 'coins', 0),
                        'reputation': getattr(value, 'reputation', 0)
                    }
                else:
                    serializable_stats[key] = str(value)
            else:
                serializable_stats[key] = value
        return jsonify(serializable_stats)
    except Exception as e:
        app.logger.error(f"Error in API stats: {e}")
        return jsonify({'error': 'Failed to load statistics'}), 500

@app.route('/shop/purchase', methods=['POST'])
def purchase_shop_item():
    """Handle shop item purchases"""
    player_nickname = session.get('player_nickname')
    if not player_nickname:
        return jsonify({'success': False, 'error': 'Необходимо войти в систему'})

    try:
        data = request.get_json()
        item_id = data.get('item_id')

        player = Player.query.filter_by(nickname=player_nickname).first()
        if not player:
            return jsonify({'success': False, 'error': 'Игрок не найден'})

        shop_item = ShopItem.query.get(item_id)
        if not shop_item or not shop_item.is_active:
            return jsonify({'success': False, 'error': 'Товар не найден'})

        # Check if already purchased
        existing_purchase = ShopPurchase.query.filter_by(
            player_id=player.id,
            item_id=item_id
        ).first()

        if existing_purchase:
            return jsonify({'success': False, 'error': 'Товар уже куплен'})

        # Check level requirement
        if player.level < shop_item.unlock_level:
            return jsonify({'success': False, 'error': f'Требуется {shop_item.unlock_level} уровень'})

        # Check currency
        if shop_item.price_coins > 0 and player.coins < shop_item.price_coins:
            return jsonify({'success': False, 'error': 'Недостаточно койнов'})

        if shop_item.price_reputation > 0 and player.reputation < shop_item.price_reputation:
            return jsonify({'success': False, 'error': 'Недостаточно репутации'})

        # Process purchase
        if shop_item.price_coins > 0:
            player.coins -= shop_item.price_coins
        if shop_item.price_reputation > 0:
            player.reputation -= shop_item.price_reputation

        # Create purchase record
        purchase = ShopPurchase(
            player_id=player.id,
            item_id=item_id,
            price_paid_coins=shop_item.price_coins,
            price_paid_reputation=shop_item.price_reputation
        )
        db.session.add(purchase)

        # Handle different item types
        if shop_item.category == 'custom_role':
            if 'basic' in shop_item.name.lower():
                player.custom_role_purchased = True
            elif 'gradient' in shop_item.name.lower():
                player.custom_role_purchased = True
                # Grant gradient access
            elif 'animated' in shop_item.name.lower():
                player.custom_role_purchased = True
                # Grant animation access
            elif 'emoji' in shop_item.name.lower():
                player.custom_role_purchased = True
                player.custom_emoji_slots += 1

        elif shop_item.category == 'theme':
            # Add theme to inventory
            player.add_inventory_item('themes', str(item_id), 1)

        elif shop_item.category == 'title':
            # Create custom title
            title_data = json.loads(shop_item.item_data) if shop_item.item_data else {}
            custom_title = CustomTitle(
                name=shop_item.name,
                display_name=shop_item.display_name,
                color=title_data.get('color', '#ffc107'),
                glow_color=title_data.get('glow_color', '#ffaa00'),
                description=shop_item.description,
                rarity=shop_item.rarity,
                is_purchasable=False
            )
            db.session.add(custom_title)
            db.session.flush()

            player_title = PlayerTitle(
                player_id=player.id,
                title_id=custom_title.id
            )
            db.session.add(player_title)

        elif shop_item.category == 'gradient':
            # Add gradient to inventory
            player.add_inventory_item('gradients', str(item_id), 1)

        elif shop_item.category == 'booster':
            # Add booster to inventory
            player.add_inventory_item('boosters', str(item_id), 1)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'{shop_item.display_name} успешно приобретен!',
            'new_coins': player.coins,
            'new_reputation': player.reputation
        })

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Purchase error: {e}")
        return jsonify({'success': False, 'error': 'Ошибка при покупке'})

@app.route('/api/toggle-admin-role', methods=['POST'])
def toggle_admin_role():
    """Toggle admin role activation"""
    player_nickname = session.get('player_nickname')
    if not player_nickname:
        return jsonify({'success': False, 'error': 'Необходимо войти в систему'}), 401

    try:
        data = request.get_json()
        role_id = data.get('role_id')
        is_active = data.get('is_active')

        player = Player.query.filter_by(nickname=player_nickname).first()
        if not player:
            return jsonify({'success': False, 'error': 'Игрок не найден'}), 404

        # Get the admin role
        from models import PlayerAdminRole
        admin_role = PlayerAdminRole.query.filter_by(
            id=role_id,
            player_id=player.id
        ).first()

        if not admin_role:
            return jsonify({'success': False, 'error': 'Роль не найдена'}), 404

        if is_active:
            # Deactivate all other admin roles for this player
            PlayerAdminRole.query.filter_by(
                player_id=player.id,
                is_active=True
            ).update({'is_active': False})

        admin_role.is_active = is_active
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Роль {"активирована" if is_active else "деактивирована"}'
        })

    except Exception as e:
        app.logger.error(f"Toggle admin role error: {e}")
        return jsonify({'success': False, 'error': 'Произошла ошибка'}), 500

@app.route('/api/player/<int:player_id>/badges')
def get_player_badges(player_id):
    """Get all badges for a player"""
    try:
        player = Player.query.get_or_404(player_id)
        player_badges = PlayerBadge.query.filter_by(player_id=player_id, is_visible=True).all()

        badges_data = []
        for pb in player_badges:
            badge = Badge.query.get(pb.badge_id)
            if badge and badge.is_active:
                badges_data.append({
                    'id': badge.id,
                    'name': badge.name,
                    'display_name': badge.display_name,
                    'icon': badge.icon,
                    'color': badge.color,
                    'background_color': badge.background_color,
                    'border_color': badge.border_color,
                    'rarity': badge.rarity,
                    'has_gradient': badge.has_gradient,
                    'gradient_start': badge.gradient_start,
                    'gradient_end': badge.gradient_end,
                    'is_animated': badge.is_animated
                })

        return jsonify({
            'success': True,
            'badges': badges_data
        })

    except Exception as e:
        app.logger.error(f"Error getting player badges: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/admin/assign_badge', methods=['POST'])
def api_assign_badge():
    """Assign badge to player via API (admin only)"""
    if not session.get('is_admin', False):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        data = request.get_json()
        player_id = data.get('player_id')
        badge_id = data.get('badge_id')

        if not player_id or not badge_id:
            return jsonify({'success': False, 'error': 'Missing player_id or badge_id'}), 400

        player = Player.query.get_or_404(player_id)
        badge = Badge.query.get_or_404(badge_id)

        # Check if player already has this badge
        existing = PlayerBadge.query.filter_by(
            player_id=player_id,
            badge_id=badge_id
        ).first()

        if existing:
            return jsonify({
                'success': False,
                'error': f'Player {player.nickname} already has badge "{badge.display_name}"'
            }), 400

        # Add badge
        player_badge = PlayerBadge(
            player_id=player_id,
            badge_id=badge_id,
            given_by='admin'
        )
        db.session.add(player_badge)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Badge "{badge.display_name}" assigned to player {player.nickname}'
        })

    except Exception as e:
        app.logger.error(f"Error assigning badge via API: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500