# Ryazhenka Bot: Intelligent Guide Management Platform for Nintendo Switch Community

Ryazhenka Bot is a comprehensive Telegram bot and web dashboard platform designed to streamline guide management, user engagement, and community knowledge sharing for the Nintendo Switch modding community. The system combines intelligent search capabilities, automated content synchronization, and advanced analytics to provide a structured, professional solution for managing guides across multiple sources.

## Core Features

### Guide Management System

The platform provides a centralized interface for managing guides across multiple categories. Administrators can create, edit, and organize guides with support for bilingual content (English and Russian). Each guide includes metadata such as creation date, update timestamp, rating statistics, and view counts. The system supports multiple source types including YouTube videos, GitHub releases, and manually added guides.

### Multi-Language Support

The dashboard interface supports both English and Russian languages with a language toggle accessible within the interface. All user-facing text, navigation menus, and documentation are available in both languages. Users can set their preferred language, which persists across sessions.

### YouTube Channel Monitoring

The system automatically monitors configured YouTube channels for new videos. Administrators can add or remove channels through the dashboard. The platform tracks synchronization status, video counts, and last sync timestamps. New videos are automatically logged and can trigger Discord notifications.

### Guide Rating System

Users can upvote or downvote guides to indicate usefulness. The system calculates aggregate ratings and sorts search results by rating. Rating statistics are displayed alongside each guide, providing social proof and helping users identify the most valuable content.

### Advanced Analytics

The analytics dashboard provides comprehensive insights into user behavior and content performance. Metrics include search query history, popular guides by view count and rating, and user activity over time. Date range filtering allows administrators to analyze trends across specific periods. Analytics data can be exported for further analysis.

### LLM-Powered Recommendations

The platform uses language models to generate personalized guide recommendations for each user based on their search history and rating patterns. Recommendations are cached for seven days to optimize performance. The system also automatically tags new guides with relevant categories using LLM analysis, reducing manual categorization work.

### Discord Integration

New guides, YouTube videos, and GitHub releases trigger formatted notifications sent to a configured Discord channel. Notifications include three key fields: title, source, and direct link. The notification system maintains a log of all sent messages and handles failures gracefully with error reporting.

### REST API for Third-Party Integration

The platform exposes a comprehensive REST API for third-party applications. API endpoints cover guide management, category browsing, YouTube channel monitoring, and analytics retrieval. Authentication uses API keys that can be generated with configurable expiration dates. All endpoints are documented with request parameters and example usage.

### Bot Settings Panel

Administrators can configure critical bot parameters through the settings interface. Configuration options include sync interval (in seconds), allowed domains for content sources, administrator IDs for access control, logging level, and Discord webhook URL for notifications.

## Technical Architecture

### Database Schema

The system uses MySQL with Drizzle ORM for data persistence. The schema includes tables for users, guides, categories, ratings, YouTube channels, search analytics, activity logs, bot settings, Discord notifications, recommendations, and API keys. All tables include appropriate indexes and constraints for data integrity.

### Backend Infrastructure

The backend is built with Express.js and tRPC for type-safe API procedures. All database queries are centralized in query helpers that handle common operations. Authentication uses Manus OAuth with role-based access control (admin/user). Protected procedures enforce authorization checks before executing sensitive operations.

### Frontend Design System

The user interface follows the International Typographic Style with a pristine white canvas, bold red accents, and crisp black sans-serif typography. The design emphasizes clean asymmetric layouts, fine black divider lines, and generous negative space. All components use a strict grid system with precise spacing and alignment.

### Internationalization

The i18n system uses a centralized translation file with support for English and Russian. Language context is provided to all React components, allowing dynamic language switching. User language preferences are persisted in the database and local storage.

## Installation and Setup

### Prerequisites

- Node.js 18 or higher
- MySQL 8.0 or higher
- Telegram Bot Token (from BotFather)
- Manus OAuth credentials
- Discord webhook URL (optional, for notifications)

### Environment Configuration

Create a `.env` file with the following variables:

```
DATABASE_URL=mysql://user:password@localhost:3306/ryazhenka
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=123456789,987654321
ALLOWED_DOMAINS=youtube.com,github.com
SYNC_INTERVAL_SECONDS=3600
LOG_LEVEL=INFO
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### Database Setup

```bash
pnpm install
pnpm drizzle-kit generate
pnpm db:push
```

### Development Server

```bash
pnpm dev
```

The development server runs on `http://localhost:3000` with hot module reloading enabled.

### Production Build

```bash
pnpm build
pnpm start
```

## API Endpoints

| Method | Endpoint | Description | Authentication |
|--------|----------|-------------|-----------------|
| GET | `/api/trpc/guides.list` | List all guides with pagination | Optional |
| POST | `/api/trpc/guides.create` | Create a new guide | Admin |
| POST | `/api/trpc/guides.update` | Update an existing guide | Admin |
| DELETE | `/api/trpc/guides.delete` | Delete a guide | Admin |
| POST | `/api/trpc/guides.rate` | Rate a guide (upvote/downvote) | User |
| GET | `/api/trpc/categories.list` | List all categories | Public |
| POST | `/api/trpc/categories.create` | Create a new category | Admin |
| GET | `/api/trpc/youtubeChannels.list` | List monitored YouTube channels | Admin |
| POST | `/api/trpc/youtubeChannels.add` | Add a YouTube channel | Admin |
| POST | `/api/trpc/youtubeChannels.remove` | Remove a YouTube channel | Admin |
| GET | `/api/trpc/analytics.searchQueries` | Get search query analytics | Admin |
| POST | `/api/trpc/analytics.logSearch` | Log a search query | Public |
| GET | `/api/trpc/settings.get` | Get a bot setting | Admin |
| POST | `/api/trpc/settings.set` | Update a bot setting | Admin |
| GET | `/api/trpc/recommendations.get` | Get personalized recommendations | User |
| GET | `/api/trpc/apiKeys.list` | List user API keys | User |
| POST | `/api/trpc/apiKeys.generate` | Generate a new API key | User |

## Authentication

All protected endpoints require authentication. For web dashboard access, use Manus OAuth. For API access, include the API key in the Authorization header:

```
Authorization: Bearer YOUR_API_KEY
```

## Deployment

### Railway Deployment

The application is configured for deployment on Railway with the following setup:

1. Connect your GitHub repository to Railway
2. Set environment variables in the Railway dashboard
3. Railway automatically builds and deploys on each push to main branch
4. The application runs as a Node.js service with automatic restarts

### Custom Deployment

For other deployment platforms, ensure the following:

- Node.js 18+ runtime
- MySQL database connection
- Environment variables properly configured
- Port 3000 exposed for the application

## Performance Optimization

The system implements several performance optimizations:

- Database query result caching for frequently accessed data
- LLM recommendation caching with 7-day expiration
- Efficient pagination for large result sets
- Indexed database queries for fast lookups
- Lazy loading of components in the React frontend

## Security Considerations

- All admin operations require role-based authorization checks
- API keys have configurable expiration dates
- Database connections use SSL/TLS encryption
- Input validation on all user-submitted data
- Rate limiting on search and API endpoints
- Secure session management with HTTP-only cookies

## Monitoring and Logging

The system maintains comprehensive logs of all operations:

- Activity log tracks user actions (create, update, delete, rate)
- Search query log records all searches for analytics
- Discord notification log tracks message delivery status
- Error logging captures exceptions with full stack traces
- Log level configuration allows adjustment of verbosity

## Troubleshooting

### Database Connection Issues

Verify the DATABASE_URL environment variable and ensure MySQL is running and accessible. Check firewall rules and network connectivity.

### Discord Notifications Not Sending

Verify the DISCORD_WEBHOOK_URL is correct and the webhook endpoint is still active. Check the Discord notification log for error messages.

### LLM Features Not Working

Ensure the LLM API credentials are properly configured. Check server logs for LLM API errors. Verify network connectivity to the LLM service.

### Performance Issues

Check database query performance using slow query logs. Consider adding indexes for frequently filtered columns. Review memory usage and consider scaling resources.

## Future Enhancements

The roadmap includes the following planned features:

- Discord bot integration for direct Discord server access
- Advanced machine learning-based recommendation engine
- Webhook support for external service integrations
- Mobile application for iOS and Android
- Real-time collaboration features for guide editing
- Advanced search with full-text indexing
- Guide versioning and change history
- User reputation system and badges

## Contributing

Contributions are welcome. Please follow these guidelines:

1. Fork the repository
2. Create a feature branch
3. Make your changes with clear commit messages
4. Submit a pull request with description of changes
5. Ensure all tests pass and code follows the style guide

## License

This project is distributed under the MIT License. See the LICENSE file for complete terms.

## Support and Contact

For bug reports, feature requests, or general questions, please use the GitHub Issues page. For urgent matters, contact the project maintainers directly through the GitHub repository.

## Acknowledgments

This project builds upon the excellent work of the Nintendo Switch Homebrew community. Special thanks to the Atmosphere project and NH Switch Guide for inspiration and reference materials.
