# Numbers - Telegram Math Bot Project Brief

## Project Overview
Numbers is a Russian-language Telegram bot designed to generate age-appropriate mathematical exercises for 3rd-grade elementary school students. The bot provides an engaging, gamified learning experience with adaptive difficulty progression.

## Core Requirements

### Functional Requirements
- Generate mathematical problems suitable for 3rd-grade students (ages 8-9)
- Support four basic operations: addition, subtraction, multiplication, and division
- Implement intelligent constraints:
  - Numbers range from 0 to 1000
  - Multiplication limited to factors ≤ 10 (for mental calculation)
  - No negative intermediate results
  - Integer-only division results
- Provide three attempts per problem with encouraging feedback
- Progressive difficulty system with 5 levels based on user performance

### Gamification Requirements
- Points system: +1 for correct answers, -1 after 3 failed attempts
- Difficulty increases every 10 points earned
- Visual feedback with emojis and encouraging messages
- Progress tracking with user state persistence

### Technical Requirements
- Telegram bot integration using aiogram framework
- State management for user sessions
- Persistent storage (Redis primary, Memory fallback)
- Docker containerization for deployment
- Comprehensive logging for monitoring

## User Experience Goals
- **Engaging**: Fun, interactive learning with positive reinforcement
- **Age-Appropriate**: Content and language suitable for 8-9 year olds
- **Accessible**: Simple Telegram interface, no additional apps needed
- **Adaptive**: Difficulty adjusts to individual skill level
- **Safe**: No personal data collection beyond necessary Telegram info

## Target Audience
- **Primary**: 3rd-grade students (ages 8-9) in Russian-speaking regions
- **Secondary**: Parents and teachers looking for supplemental math practice tools

## Success Metrics
- User engagement (daily active users, problems solved)
- Learning progression (difficulty level advancement)
- User retention (return usage patterns)
- Technical reliability (uptime, error rates)

## Project Scope
The project focuses specifically on mental arithmetic skills development through:
- Structured problem generation with pedagogical constraints
- Adaptive learning algorithms
- Engaging user interaction design
- Reliable technical infrastructure

## Constraints and Limitations
- Russian language interface only
- Single player mode (no multiplayer or competition features)
- No advanced mathematics (fractions, decimals, geometry)
- Telegram platform dependency
- No curriculum alignment beyond basic arithmetic progression

## Success Criteria
1. Functional bot that generates appropriate math problems
2. Adaptive difficulty system working correctly
3. Engaging user experience with positive feedback
4. Reliable deployment with minimal downtime
5. Positive user feedback and continued usage