#include "skaddon.h"
#include <cmath>
#include <vector>
#include <string>
#include <algorithm>

// ============================================================================
// 1. 데이터 구조체 정의
// ============================================================================

enum class CharacterClass {
    GUARDIAN, FIGHTER, ARCHER, ROGUE, MAGICIAN, CLERIC
};

enum class EffectType { BUFF_ATK, DEBUFF_DEF, DOT_POISON, HOT_REGEN, STUN };

struct StatusEffect {
    EffectType type;
    std::string name;
    float duration, tickInterval, tickTimer, value;
};

struct AttackHitbox {
    bool isActive = false;
    float x = 0.0f, y = 0.0f, z = 0.0f;
    float radius = 1.5f;
    float damage = 150.0f;
};

struct ActionCharacter {
    int id = 0;
    CharacterClass charClass;
    float x = 0.0f, y = 0.0f, z = 0.0f;
    float radius = 1.0f;
    float speed = 4.0f;
    
    float hp = 1000.0f, maxHp = 1000.0f;
    float baseAtk = 100.0f, currentAtk = 100.0f;
    float baseDef = 50.0f, currentDef = 50.0f;
    
    float aggroPoint = 0.0f, aggroPercent = 0.0f;
    float currentStamina = 100.0f, maxStamina = 100.0f;
    bool isDodging = false, isDefending = false;
    float dodgeTimer = 0.0f;
    float actionCooldown = 0.0f; 

    std::vector<StatusEffect> activeEffects;
};

struct ActionEnemy {
    int id = 0;
    float x = 0.0f, y = 0.0f, z = 10.0f;
    float hp = 2000.0f;
    float radius = 1.5f;
    float speed = 3.0f;
    float attackCooldown = 0.0f;
    int targetPlayerId = -1; 
    AttackHitbox currentAttack;
    std::vector<std::string> dropItems;
};

struct ActionLogEvent {
    int sourceId;
    int targetId;
    std::string actionName; 
};

struct ActionBattleDirector {
    bool isRunning = false;
    bool isBattleFinished = false; 
    
    int controlledPlayerId = 1; 
    std::vector<ActionCharacter> party;
    std::vector<ActionEnemy> enemies;
    
    std::vector<std::string> earnedRewards; 
    std::vector<ActionLogEvent> frameEvents; 
    int lockOnTargetId = -1;

    // --- [NEW] 파티 연계기 (Burst Chain) 데이터 ---
    float partyBurstGauge = 0.0f;
    float maxBurstGauge = 100.0f;
    bool isChainAttackMode = false;
    int chainStep = 0;          // 1~4: 각 캐릭터 컷신, 5: 종료
    float chainTimer = 0.0f;    // 각 컷신의 지속 시간 타이머
} g_Director;

// ============================================================================
// 2. 헬퍼 연산 함수
// ============================================================================

float GetDistance3D(float x1, float y1, float z1, float x2, float y2, float z2) {
    return std::sqrt((x1 - x2)*(x1 - x2) + (y1 - y2)*(y1 - y2) + (z1 - z2)*(z1 - z2));
}

void MoveToMaintainDistance(float& x, float& z, float tx, float tz, float speed, float dt, float targetDist, bool isKite = false) {
    float dx = tx - x;
    float dz = tz - z;
    float dist = std::sqrt(dx*dx + dz*dz);
    if (dist == 0.0f) return;

    if (isKite && dist < targetDist) {
        x -= (dx/dist) * speed * dt;
        z -= (dz/dist) * speed * dt;
    } else if (dist > targetDist) {
        x += (dx/dist) * speed * dt;
        z += (dz/dist) * speed * dt;
    }
}

void NormalizeAggro() {
    float totalAggro = 0.0f;
    for (const auto& p : g_Director.party) {
        if (p.hp > 0.0f) totalAggro += p.aggroPoint;
    }
    if (totalAggro <= 0.0f) return;
    for (auto& p : g_Director.party) {
        if (p.hp > 0.0f) p.aggroPercent = (p.aggroPoint / totalAggro) * 100.0f;
        else p.aggroPercent = 0.0f;
    }
}

void UpdateEnemyAI(float dt, ActionEnemy& enemy) {
    float highestAggro = -1.0f;
    ActionCharacter* target = nullptr;
    
    for (auto& p : g_Director.party) {
        if (p.hp > 0.0f && p.aggroPercent > highestAggro) {
            highestAggro = p.aggroPercent;
            enemy.targetPlayerId = p.id;
            target = &p;
        }
    }
    
    if (target != nullptr) {
        float dist = GetDistance3D(enemy.x, enemy.y, enemy.z, target->x, target->y, target->z);
        if (dist > (enemy.radius + target->radius + 0.5f)) {
            MoveToMaintainDistance(enemy.x, enemy.z, target->x, target->z, enemy.speed, dt, enemy.radius + target->radius);
        } else {
            if (!enemy.currentAttack.isActive && enemy.attackCooldown <= 0.0f) {
                enemy.currentAttack.isActive = true;
                enemy.currentAttack.x = target->x;
                enemy.currentAttack.z = target->z;
                enemy.attackCooldown = 2.0f; 
            }
        }
    }
    if (enemy.attackCooldown > 0.0f) enemy.attackCooldown -= dt;
}

void UpdatePartyAI(float dt) {
    if (g_Director.enemies.empty()) return;
    ActionEnemy& boss = g_Director.enemies[0]; 

    float maxPartyAggro = 0.0f;
    for (const auto& p : g_Director.party) {
        if (p.hp > 0.0f && p.aggroPercent > maxPartyAggro) maxPartyAggro = p.aggroPercent;
    }

    for (auto& p : g_Director.party) {
        if (p.hp <= 0.0f || p.id == g_Director.controlledPlayerId) continue;
        
        p.isDefending = false;
        if (p.actionCooldown > 0.0f) p.actionCooldown -= dt;
        
        float distToBoss = GetDistance3D(p.x, p.y, p.z, boss.x, boss.y, boss.z);

        switch (p.charClass) {
            case CharacterClass::GUARDIAN: {
                if (p.hp < p.maxHp * 0.3f) p.isDefending = true;
                else {
                    MoveToMaintainDistance(p.x, p.z, boss.x, boss.z, p.speed, dt, 2.0f, false);
                    if (p.actionCooldown <= 0.0f) {
                        if (p.aggroPercent < maxPartyAggro) {
                            p.aggroPoint += 50.0f; 
                            g_Director.frameEvents.push_back({p.id, boss.id, "PROVOKE"});
                            p.actionCooldown = 4.0f;
                        } else if (distToBoss <= 2.5f) {
                            boss.hp -= p.currentAtk; 
                            g_Director.frameEvents.push_back({p.id, boss.id, "ATTACK_MELEE"});
                            p.actionCooldown = 2.0f;
                            g_Director.partyBurstGauge += 2.0f; // AI 공격 시 버스트 게이지 소폭 상승
                        }
                    }
                }
                break;
            }
            case CharacterClass::FIGHTER: {
                MoveToMaintainDistance(p.x, p.z, boss.x, boss.z, p.speed, dt, 2.0f, false);
                if (p.actionCooldown <= 0.0f && distToBoss <= 2.5f) {
                    boss.hp -= (p.currentAtk * 1.5f); 
                    g_Director.frameEvents.push_back({p.id, boss.id, "ATTACK_MELEE"});
                    p.actionCooldown = 1.5f;
                    g_Director.partyBurstGauge += 2.0f;
                }
                break;
            }
            case CharacterClass::ARCHER: 
            case CharacterClass::MAGICIAN: {
                MoveToMaintainDistance(p.x, p.z, boss.x, boss.z, p.speed, dt, 8.0f, true);
                if (p.actionCooldown <= 0.0f && distToBoss <= 10.0f) {
                    boss.hp -= p.currentAtk;
                    std::string actName = (p.charClass == CharacterClass::ARCHER) ? "ATTACK_ARROW" : "ATTACK_MAGIC";
                    g_Director.frameEvents.push_back({p.id, boss.id, actName});
                    p.actionCooldown = 2.0f;
                    g_Director.partyBurstGauge += 2.0f;
                }
                break;
            }
            case CharacterClass::CLERIC: {
                ActionCharacter* lowestHpAlly = nullptr;
                float lowestHpRatio = 1.0f;
                for (auto& ally : g_Director.party) {
                    if (ally.hp > 0.0f && (ally.hp / ally.maxHp) < lowestHpRatio) {
                        lowestHpRatio = (ally.hp / ally.maxHp);
                        lowestHpAlly = &ally;
                    }
                }

                if (lowestHpAlly != nullptr && lowestHpRatio < 0.6f) {
                    float distToAlly = GetDistance3D(p.x, p.y, p.z, lowestHpAlly->x, lowestHpAlly->y, lowestHpAlly->z);
                    MoveToMaintainDistance(p.x, p.z, lowestHpAlly->x, lowestHpAlly->z, p.speed, dt, 4.0f, false);
                    if (p.actionCooldown <= 0.0f && distToAlly <= 5.0f) {
                        lowestHpAlly->hp += 300.0f; 
                        if (lowestHpAlly->hp > lowestHpAlly->maxHp) lowestHpAlly->hp = lowestHpAlly->maxHp;
                        g_Director.frameEvents.push_back({p.id, lowestHpAlly->id, "HEAL_MAGIC"});
                        p.actionCooldown = 4.0f;
                    }
                } else {
                    MoveToMaintainDistance(p.x, p.z, boss.x, boss.z, p.speed, dt, 8.0f, true);
                    if (p.actionCooldown <= 0.0f && distToBoss <= 10.0f) {
                        boss.hp -= p.currentAtk;
                        g_Director.frameEvents.push_back({p.id, boss.id, "ATTACK_MAGIC"});
                        p.actionCooldown = 3.0f;
                        g_Director.partyBurstGauge += 2.0f;
                    }
                }
                break;
            }
            default: break;
        }
    }
    NormalizeAggro(); 
}

void ProcessStatusEffects(float dt, ActionCharacter& character, bool& outPoisonTick, bool& outRegenTick) {
    character.currentAtk = character.baseAtk;
    character.currentDef = character.baseDef;

    for (auto it = character.activeEffects.begin(); it != character.activeEffects.end(); ) {
        it->duration -= dt;
        if (it->type == EffectType::DOT_POISON || it->type == EffectType::HOT_REGEN) {
            it->tickTimer -= dt;
            if (it->tickTimer <= 0.0f) {
                if (it->type == EffectType::DOT_POISON) {
                    character.hp -= it->value;
                    outPoisonTick = true;
                } else if (it->type == EffectType::HOT_REGEN) {
                    character.hp += it->value;
                    if (character.hp > character.maxHp) character.hp = character.maxHp;
                    outRegenTick = true;
                }
                it->tickTimer = it->tickInterval; 
            }
        }
        if (it->type == EffectType::BUFF_ATK) character.currentAtk += it->value;
        if (it->type == EffectType::DEBUFF_DEF) character.currentDef -= it->value;

        if (it->duration <= 0.0f) it = character.activeEffects.erase(it);
        else ++it;
    }
}

// ============================================================================
// 3. SK 엔진 바인딩 함수 (Exported API)
// ============================================================================

extern "C" int SK_InitBattleScene(SKVM* vm) {
    g_Director.isRunning = true;
    g_Director.isBattleFinished = false;
    g_Director.earnedRewards.clear();
    
    g_Director.partyBurstGauge = 0.0f;
    g_Director.isChainAttackMode = false;
    g_Director.chainStep = 0;
    
    g_Director.party.clear();
    g_Director.enemies.clear();
    g_Director.lockOnTargetId = -1;
    g_Director.controlledPlayerId = 1; 
    
    ActionCharacter guardian; guardian.id = 1; guardian.charClass = CharacterClass::GUARDIAN; guardian.aggroPoint = 44.0f; guardian.x = -2.0f;
    ActionCharacter fighter; fighter.id = 2; fighter.charClass = CharacterClass::FIGHTER; fighter.aggroPoint = 22.0f; fighter.x = 2.0f;
    ActionCharacter archer; archer.id = 3; archer.charClass = CharacterClass::ARCHER; archer.aggroPoint = 22.0f; archer.x = -4.0f; archer.z = -3.0f;
    ActionCharacter cleric; cleric.id = 4; cleric.charClass = CharacterClass::CLERIC; cleric.aggroPoint = 22.0f; cleric.x = 4.0f; cleric.z = -3.0f;
    
    g_Director.party.push_back(guardian);
    g_Director.party.push_back(fighter);
    g_Director.party.push_back(archer);
    g_Director.party.push_back(cleric);
    NormalizeAggro();
    
    ActionEnemy boss; boss.id = 100; boss.z = 15.0f; boss.hp = 2000.0f;
    boss.dropItems.push_back("Ultimate_Weapon");
    boss.dropItems.push_back("Gold_Coin_x1000");
    g_Director.enemies.push_back(boss);
    
    return 0;
}

extern "C" int SK_SwapCharacter(SKVM* vm) {
    int nextId = SK_GetInt(vm, 1);
    for (const auto& p : g_Director.party) {
        if (p.id == nextId && p.hp > 0) {
            g_Director.controlledPlayerId = nextId;
            break;
        }
    }
    return 0;
}

extern "C" int SK_AddAggro(SKVM* vm) {
    int charId = SK_GetInt(vm, 1);
    float amount = SK_GetFloat(vm, 2);
    for (auto& p : g_Director.party) {
        if (p.id == charId) { p.aggroPoint += amount; break; }
    }
    NormalizeAggro();
    return 0;
}

extern "C" int SK_ToggleLockOn(SKVM* vm) {
    if (g_Director.enemies.empty()) { SK_PushInt(vm, -1); return 1; }
    if (g_Director.lockOnTargetId == -1) g_Director.lockOnTargetId = g_Director.enemies[0].id;
    else g_Director.lockOnTargetId = -1;
    SK_PushInt(vm, g_Director.lockOnTargetId);
    return 1;
}

extern "C" int SK_ApplyPoisonToPlayer(SKVM* vm) {
    for (auto& p : g_Director.party) {
        if (p.id == g_Director.controlledPlayerId) {
            StatusEffect poison = { EffectType::DOT_POISON, "Poison", 10.0f, 1.0f, 1.0f, 15.0f };
            p.activeEffects.push_back(poison);
            break;
        }
    }
    return 0;
}

// 메인 업데이트 (모든 로직 통합)
extern "C" int SK_UpdateBattleScene(SKVM* vm) {
    float dt = SK_GetFloat(vm, 1);
    bool inputDodge = SK_GetBool(vm, 2);
    bool inputBurst = SK_GetBool(vm, 3); // [NEW] 버스트 스킬 입력
    
    if (!g_Director.isRunning) { SK_PushNull(vm); return 1; }

    g_Director.frameEvents.clear(); 
    bool eventTookDamage = false;
    bool eventJustDodge = false;
    bool eventPoisonTick = false;
    bool eventRegenTick = false;
    bool eventChainStepStart = false; // [NEW] 컷신 스텝이 변경된 첫 프레임인지 여부
    
    // --- [NEW] 파티 연계기 (Chain Attack) 상태 머신 ---
    if (g_Director.isChainAttackMode) {
        // 연계기 중에는 적 AI, 파티 AI, 도트 데미지 등 모든 일반 시간이 정지됨(Time Stop)
        g_Director.chainTimer -= dt;
        
        if (g_Director.chainTimer <= 0.0f) {
            g_Director.chainStep++;       // 다음 캐릭터로 컷신 전환
            g_Director.chainTimer = 2.0f; // 각 캐릭터당 2초간 컷신 연출
            eventChainStepStart = true;
            
            // 4명의 연출이 모두 끝나면 (Step 5)
            if (g_Director.chainStep > 4) {
                g_Director.isChainAttackMode = false;
                g_Director.chainStep = 0;
                g_Director.partyBurstGauge = 0.0f; // 게이지 초기화
                
                // 보스에게 궁극기 합산 데미지 일괄 적용
                if (!g_Director.enemies.empty()) {
                    g_Director.enemies[0].hp -= 1500.0f; 
                }
            }
        }
    } 
    else {
        // --- 일반 전투 모드 ---
        
        // 게이지가 다 찼고 발동 키를 눌렀다면 연계기 진입!
        if (inputBurst && g_Director.partyBurstGauge >= g_Director.maxBurstGauge && !g_Director.enemies.empty()) {
            g_Director.isChainAttackMode = true;
            g_Director.chainStep = 1;
            g_Director.chainTimer = 2.0f;
            eventChainStepStart = true;
        }
        
        // --- [적 사망 및 전투 종료 처리] ---
        for (auto it = g_Director.enemies.begin(); it != g_Director.enemies.end(); ) {
            if (it->hp <= 0.0f) {
                for (const auto& item : it->dropItems) g_Director.earnedRewards.push_back(item);
                if (g_Director.lockOnTargetId == it->id) g_Director.lockOnTargetId = -1;
                it = g_Director.enemies.erase(it);
            } else { ++it; }
        }

        if (g_Director.enemies.empty() && !g_Director.isBattleFinished) {
            g_Director.isBattleFinished = true; 
        }

        // --- AI 및 캐릭터 업데이트 ---
        if (!g_Director.isBattleFinished) {
            if (!g_Director.enemies.empty()) {
                UpdateEnemyAI(dt, g_Director.enemies[0]);
            }
            UpdatePartyAI(dt);
        }

        ActionCharacter* controlledPlayer = nullptr;
        for (auto& p : g_Director.party) {
            if (p.id == g_Director.controlledPlayerId) { controlledPlayer = &p; break; }
        }

        if (controlledPlayer && !g_Director.isBattleFinished) {
            ProcessStatusEffects(dt, *controlledPlayer, eventPoisonTick, eventRegenTick);

            bool isStunned = false;
            for (const auto& eff : controlledPlayer->activeEffects) {
                if (eff.type == EffectType::STUN) { isStunned = true; break; }
            }

            if (!isStunned) {
                if (controlledPlayer->isDodging) {
                    controlledPlayer->dodgeTimer -= dt;
                    if (controlledPlayer->dodgeTimer <= 0.0f) controlledPlayer->isDodging = false;
                } else {
                    if (controlledPlayer->currentStamina < controlledPlayer->maxStamina) {
                        controlledPlayer->currentStamina += (20.0f * dt);
                        if (controlledPlayer->currentStamina > controlledPlayer->maxStamina) 
                            controlledPlayer->currentStamina = controlledPlayer->maxStamina;
                    }
                    if (inputDodge && controlledPlayer->currentStamina >= 50.0f) {
                        controlledPlayer->currentStamina -= 50.0f;
                        controlledPlayer->isDodging = true;
                        controlledPlayer->dodgeTimer = 0.4f;
                    }
                }
            }

            // 적 -> 플레이어 충돌 및 저스트 회피 판정
            if (!g_Director.enemies.empty() && g_Director.enemies[0].currentAttack.isActive) {
                AttackHitbox& attack = g_Director.enemies[0].currentAttack;
                float dist = GetDistance3D(controlledPlayer->x, controlledPlayer->y, controlledPlayer->z, attack.x, attack.y, attack.z);
                
                if (dist < (controlledPlayer->radius + attack.radius)) {
                    if (controlledPlayer->isDodging && controlledPlayer->dodgeTimer > 0.3f) { 
                        eventJustDodge = true;
                        attack.isActive = false; 
                        
                        // [NEW] 저스트 회피 성공 시 버스트 게이지 대폭 상승
                        g_Director.partyBurstGauge += 20.0f; 
                    } else if (!controlledPlayer->isDodging && !controlledPlayer->isDefending) {
                        float finalDamage = attack.damage - controlledPlayer->currentDef;
                        if (finalDamage < 1.0f) finalDamage = 1.0f;
                        controlledPlayer->hp -= finalDamage;
                        eventTookDamage = true;
                        attack.isActive = false;
                        
                        // [NEW] 피격 시에도 버스트 게이지 소폭 상승
                        g_Director.partyBurstGauge += 5.0f;
                    }
                }
            }
        }
        
        // 게이지가 최대치를 넘지 않도록 보정
        if (g_Director.partyBurstGauge > g_Director.maxBurstGauge) {
            g_Director.partyBurstGauge = g_Director.maxBurstGauge;
        }
    } // End of Normal Mode (else block)

    // --- 카메라 위치 연산 ---
    float camPosX = 0.0f, camPosY = 5.0f, camPosZ = 0.0f;
    float lookAtX = 0.0f, lookAtY = 0.0f, lookAtZ = 0.0f;
    
    // 연계기 중일 때: 현재 컷신 스텝의 주연 캐릭터를 클로즈업
    if (g_Director.isChainAttackMode && g_Director.chainStep >= 1 && g_Director.chainStep <= 4) {
        ActionCharacter& actor = g_Director.party[g_Director.chainStep - 1]; // 0~3 인덱스 (가디언~클레릭)
        lookAtX = actor.x; lookAtY = actor.y + 1.0f; lookAtZ = actor.z;
        camPosX = actor.x + 2.0f; // 정면 클로즈업 오프셋
        camPosY = actor.y + 2.0f;
        camPosZ = actor.z + 3.0f;
    } 
    // 일반 모드일 때: 조작 캐릭터 기준 오프셋 록온
    else {
        ActionCharacter* controlledPlayer = nullptr;
        for (auto& p : g_Director.party) {
            if (p.id == g_Director.controlledPlayerId) { controlledPlayer = &p; break; }
        }
        
        if (controlledPlayer) {
            camPosX = controlledPlayer->x; camPosY = controlledPlayer->y + 5.0f; camPosZ = controlledPlayer->z - 5.0f;
            lookAtX = controlledPlayer->x; lookAtY = controlledPlayer->y; lookAtZ = controlledPlayer->z;
            
            if (g_Director.lockOnTargetId != -1 && !g_Director.enemies.empty()) {
                lookAtX = (controlledPlayer->x + g_Director.enemies[0].x) / 2.0f;
                lookAtZ = (controlledPlayer->z + g_Director.enemies[0].z) / 2.0f;
                camPosX = controlledPlayer->x - 4.0f; 
                camPosZ = controlledPlayer->z - 8.0f;
            }
        }
    }

    // ============================================================================
    // 스크립트 반환(Table) 구성
    // ============================================================================
    SK_NewTable(vm); //[cite: 4]
    
    // 연계기(Burst) 상태 정보 반환
    SK_PushString(vm, "burstGauge"); SK_PushFloat(vm, g_Director.partyBurstGauge); SK_SetSlot(vm, -3); //[cite: 4]
    SK_PushString(vm, "isChainAttackMode"); SK_PushBool(vm, g_Director.isChainAttackMode); SK_SetSlot(vm, -3);
    SK_PushString(vm, "chainStep"); SK_PushInt(vm, g_Director.chainStep); SK_SetSlot(vm, -3);
    SK_PushString(vm, "eventChainStepStart"); SK_PushBool(vm, eventChainStepStart); SK_SetSlot(vm, -3);

    SK_PushString(vm, "isBattleFinished"); SK_PushBool(vm, g_Director.isBattleFinished); SK_SetSlot(vm, -3);
    SK_PushString(vm, "earnedRewards");
    SK_NewArray(vm, 0); //[cite: 4]
    for (const auto& item : g_Director.earnedRewards) {
        SK_PushString(vm, item.c_str()); SK_ArrayPush(vm, -2); //[cite: 4]
    }
    SK_SetSlot(vm, -3);

    ActionCharacter* controlledPlayer = nullptr;
    for (auto& p : g_Director.party) {
        if (p.id == g_Director.controlledPlayerId) { controlledPlayer = &p; break; }
    }

    if (controlledPlayer) {
        SK_PushString(vm, "hp"); SK_PushFloat(vm, controlledPlayer->hp); SK_SetSlot(vm, -3); 
        SK_PushString(vm, "stamina"); SK_PushFloat(vm, controlledPlayer->currentStamina); SK_SetSlot(vm, -3);
        SK_PushString(vm, "isDodging"); SK_PushBool(vm, controlledPlayer->isDodging); SK_SetSlot(vm, -3);
        SK_PushString(vm, "controlledId"); SK_PushInt(vm, controlledPlayer->id); SK_SetSlot(vm, -3);
        
        bool isStunned = false;
        for (const auto& eff : controlledPlayer->activeEffects) { if (eff.type == EffectType::STUN) isStunned = true; }
        SK_PushString(vm, "isStunned"); SK_PushBool(vm, isStunned); SK_SetSlot(vm, -3);

        SK_PushString(vm, "effectNames");
        SK_NewArray(vm, 0); 
        for (const auto& eff : controlledPlayer->activeEffects) {
            SK_PushString(vm, eff.name.c_str()); SK_ArrayPush(vm, -2); 
        }
        SK_SetSlot(vm, -3);
    }

    SK_PushString(vm, "eventTookDamage"); SK_PushBool(vm, eventTookDamage); SK_SetSlot(vm, -3);
    SK_PushString(vm, "eventJustDodge"); SK_PushBool(vm, eventJustDodge); SK_SetSlot(vm, -3);
    SK_PushString(vm, "eventPoisonTick"); SK_PushBool(vm, eventPoisonTick); SK_SetSlot(vm, -3);
    SK_PushString(vm, "eventRegenTick"); SK_PushBool(vm, eventRegenTick); SK_SetSlot(vm, -3);

    SK_PushString(vm, "aiActions");
    SK_NewArray(vm, 0); 
    for (const auto& log : g_Director.frameEvents) {
        SK_NewTable(vm); 
        SK_PushString(vm, "src"); SK_PushInt(vm, log.sourceId); SK_SetSlot(vm, -3);
        SK_PushString(vm, "target"); SK_PushInt(vm, log.targetId); SK_SetSlot(vm, -3);
        SK_PushString(vm, "action"); SK_PushString(vm, log.actionName.c_str()); SK_SetSlot(vm, -3);
        SK_ArrayPush(vm, -2); 
    }
    SK_SetSlot(vm, -3);

    SK_PushString(vm, "partyAggro");
    SK_NewArray(vm, 0); 
    for (const auto& p : g_Director.party) {
        SK_PushFloat(vm, p.aggroPercent); SK_ArrayPush(vm, -2); 
    }
    SK_SetSlot(vm, -3);
    
    SK_PushString(vm, "enemyTargetId");
    if (!g_Director.enemies.empty()) SK_PushInt(vm, g_Director.enemies[0].targetPlayerId);
    else SK_PushInt(vm, -1);
    SK_SetSlot(vm, -3);

    SK_PushString(vm, "camPos"); SK_NewArray(vm, 0); 
    SK_PushFloat(vm, camPosX); SK_ArrayPush(vm, -2); SK_PushFloat(vm, camPosY); SK_ArrayPush(vm, -2); SK_PushFloat(vm, camPosZ); SK_ArrayPush(vm, -2);
    SK_SetSlot(vm, -3);

    SK_PushString(vm, "lookAt"); SK_NewArray(vm, 0); 
    SK_PushFloat(vm, lookAtX); SK_ArrayPush(vm, -2); SK_PushFloat(vm, lookAtY); SK_ArrayPush(vm, -2); SK_PushFloat(vm, lookAtZ); SK_ArrayPush(vm, -2);
    SK_SetSlot(vm, -3);

    return 1;
}

extern "C" __declspec(dllexport) bool SKAddon_Init(SKVM* vm) {
    SK_RegisterGlobalFunction(vm, "Native_InitBattleScene", SK_InitBattleScene);
    SK_RegisterGlobalFunction(vm, "Native_UpdateBattleScene", SK_UpdateBattleScene);
    SK_RegisterGlobalFunction(vm, "Native_ToggleLockOn", SK_ToggleLockOn);
    SK_RegisterGlobalFunction(vm, "Native_SwapCharacter", SK_SwapCharacter);
    SK_RegisterGlobalFunction(vm, "Native_AddAggro", SK_AddAggro);
    SK_RegisterGlobalFunction(vm, "Native_ApplyPoisonToPlayer", SK_ApplyPoisonToPlayer);
    return true;
}