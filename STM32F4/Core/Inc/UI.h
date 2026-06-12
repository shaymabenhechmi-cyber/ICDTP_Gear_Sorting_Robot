/*
 * UI.h
 *
 *  Created on: Sep 10, 2025
 *      Author: jakob
 *
 *  Serial protocol for Pi <-> STM32 communication.
 *  Pi sends 19-byte command frames, STM32 replies with 23-byte status frames.
 */

#ifndef INC_UI_H_
#define INC_UI_H_

#include "motor/motor_types.h"
#include <string.h>

/* ── Frame constants ─────────────────────────────────────────────────── */
#define RX_FRAME_SIZE   19
#define TX_FRAME_SIZE   23
#define START_RX        0xAA
#define START_TX        0xBB

/* ── Command IDs (Pi → STM32) ───────────────────────────────────────── */
typedef enum
{
	CMD_STREAM_POS   = 0x01,  // 4× int32 target steps (periodic ~50ms)
	CMD_RESET        = 0x02,  // StallGuard homing all 5 motors
	CMD_HOME         = 0x03,  // Move to predefined home steps (4× int32)
	CMD_GRIP_OPEN    = 0x04,  // Open gripper (Motor 5)
	CMD_GRIP_CLOSE   = 0x05,  // Close gripper (Motor 5)
	CMD_ESTOP        = 0x06   // Emergency stop all motors
} cmd_id_t;

/* ── Status flag bits (STM32 → Pi) ──────────────────────────────────── */
#define FLAG_M1_MOVING      (1 << 0)
#define FLAG_M2_MOVING      (1 << 1)
#define FLAG_M3_MOVING      (1 << 2)
#define FLAG_M4_MOVING      (1 << 3)
#define FLAG_M5_MOVING      (1 << 4)
#define FLAG_M5_STALL       (1 << 5)  // Gripper stall detected (object gripped / endstop)
#define FLAG_HOMING_DONE    (1 << 6)
#define FLAG_ERROR          (1 << 7)

/* ── Shared volatile state (set by RX ISR, consumed by main loop) ──── */
extern volatile int32_t  target_steps[4];
extern volatile uint8_t  new_target_flag;
extern volatile uint8_t  gripper_cmd;     // 0=none, CMD_GRIP_OPEN or CMD_GRIP_CLOSE
extern volatile uint8_t  reset_request;
extern volatile uint8_t  home_request;
extern volatile int32_t  home_steps[4];
extern volatile uint8_t  estop_request;
extern volatile uint8_t  homing_done_flag;
extern volatile uint8_t  error_flag;

extern uint8_t rx_buf[RX_FRAME_SIZE];

/* ── Function prototypes ────────────────────────────────────────────── */
uint8_t crc8_xor(uint8_t *data, uint8_t len);
void    sendStatusReport(void);
void    startSerialReceive(void);

#endif /* INC_UI_H_ */
