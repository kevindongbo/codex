(function (root) {
  'use strict';

  const SESSION_KEY = 'dongbo.team.session.v1';
  const LOCAL_WAREHOUSE_ID = 'warehouse-default';
  const CAPABILITY_KEYS = {
    catalog: 'catalog',
    warehouse_admin: 'warehouse',
    purchase: 'purchase',
    receipt: 'warehouse',
    inventory: 'warehouse',
    transfer: 'warehouse',
    order: 'order',
    return: 'order',
    competitor: 'catalog',
    selection: 'catalog',
    replenishment: 'replenishment',
    migration: 'data'
  };

  class ApiError extends Error {
    constructor(message, status, data) {
      super(message || '请求失败');
      this.name = 'ApiError';
      this.status = status || 0;
      this.data = data || null;
    }
  }

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function iso(value) {
    if (!value) return null;
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
  }

  function errorMessage(data, fallback) {
    if (!data) return fallback || '请求失败，请重试。';
    if (typeof data === 'string') return data;
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data)) return data.map(function (item) { return errorMessage(item, ''); }).filter(Boolean).join('；');
    const messages = [];
    Object.keys(data).forEach(function (key) {
      const value = data[key];
      const text = Array.isArray(value)
        ? value.map(function (item) { return errorMessage(item, String(item)); }).join('、')
        : errorMessage(value, String(value));
      if (text) messages.push((key === 'non_field_errors' ? '' : key + '：') + text);
    });
    return messages.join('；') || fallback || '请求失败，请重试。';
  }

  function randomKey(prefix) {
    const suffix = root.crypto && typeof root.crypto.randomUUID === 'function'
      ? root.crypto.randomUUID()
      : Date.now() + '-' + Math.random().toString(36).slice(2);
    return prefix + ':' + suffix;
  }

  function pageItems(payload) {
    if (Array.isArray(payload)) return payload;
    return payload && Array.isArray(payload.results) ? payload.results : [];
  }

  class TeamGateway {
    constructor(config) {
      this.config = Object.assign({ apiBase: '/api' }, config || {});
      this.apiBase = String(this.config.apiBase || '/api').replace(/\/$/, '');
      this.accessToken = '';
      this.refreshToken = '';
      this.refreshPromise = null;
      this.user = null;
      this.memberships = [];
      this.organizationId = '';
      this.warehouseId = '';
      this.role = '';
      this.permissions = [];
      this.emailVerificationEnabled = false;
      this.syncRevision = 0;
      this.warehouses = [];
      this.cache = {};
      this.pendingIdempotency = new Map();
      this.online = root.navigator ? root.navigator.onLine !== false : true;
      this.restoreSessionSelection();
    }

    restoreSessionSelection() {
      try {
        const saved = JSON.parse(root.sessionStorage.getItem(SESSION_KEY) || '{}');
        this.refreshToken = String(saved.refreshToken || '');
        this.organizationId = String(saved.organizationId || '');
        this.warehouseId = String(saved.warehouseId || '');
      } catch (_) {
        this.refreshToken = '';
      }
    }

    persistSessionSelection() {
      try {
        root.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
          refreshToken: this.refreshToken,
          organizationId: this.organizationId,
          warehouseId: this.warehouseId
        }));
      } catch (_) { /* session remains usable in memory */ }
    }

    clearSession() {
      this.accessToken = '';
      this.refreshToken = '';
      this.user = null;
      this.memberships = [];
      this.organizationId = '';
      this.warehouseId = '';
      this.role = '';
      this.permissions = [];
      this.emailVerificationEnabled = false;
      this.syncRevision = 0;
      this.warehouses = [];
      this.cache = {};
      this.pendingIdempotency.clear();
      try { root.sessionStorage.removeItem(SESSION_KEY); } catch (_) { /* noop */ }
    }

    buildUrl(path) {
      if (/^https?:\/\//i.test(path)) return path;
      if (path === this.apiBase || path.indexOf(this.apiBase + '/') === 0) return path;
      return this.apiBase + (path.charAt(0) === '/' ? path : '/' + path);
    }

    async request(path, options) {
      const settings = Object.assign({ method: 'GET', auth: true, organization: true, retry: true }, options || {});
      const headers = Object.assign({ Accept: 'application/json' }, settings.headers || {});
      if (settings.auth && this.accessToken) headers.Authorization = 'Bearer ' + this.accessToken;
      if (settings.organization && this.organizationId) headers['X-Organization-ID'] = this.organizationId;
      let body = settings.body;
      const isFormData = Boolean(root.FormData && body instanceof root.FormData);
      if (body != null && !isFormData && typeof body !== 'string') {
        headers['Content-Type'] = 'application/json';
        body = JSON.stringify(body);
      }
      let response;
      try {
        response = await root.fetch(this.buildUrl(path), {
          method: settings.method,
          headers: headers,
          body: body,
          credentials: 'same-origin'
        });
        this.online = true;
      } catch (error) {
        this.online = false;
        throw new ApiError('无法连接团队服务器，当前数据保持只读。', 0, { cause: error && error.message });
      }
      if (response.status === 401 && settings.auth && settings.retry && this.refreshToken) {
        await this.refreshAccessToken();
        return this.request(path, Object.assign({}, settings, { retry: false }));
      }
      const contentType = response.headers.get('content-type') || '';
      let payload = null;
      if (response.status !== 204) {
        payload = contentType.includes('application/json') ? await response.json() : await response.text();
      }
      if (!response.ok) throw new ApiError(errorMessage(payload, '请求失败。'), response.status, payload);
      return payload;
    }

    async login(username, password) {
      const payload = await this.request('/auth/token/', {
        method: 'POST', auth: false, organization: false,
        body: { username: username, password: password }
      });
      if (payload && payload.email_verification_required) return payload;
      this.accessToken = payload.access;
      this.refreshToken = payload.refresh;
      await this.bootstrapIdentity();
      this.persistSessionSelection();
      return this.loadState();
    }

    async verifyOwnerLogin(challengeId, code) {
      const payload = await this.request('/auth/owner/login/verify/', {
        method: 'POST', auth: false, organization: false,
        body: { challenge_id: challengeId, code: code }
      });
      this.accessToken = payload.access;
      this.refreshToken = payload.refresh;
      await this.bootstrapIdentity();
      this.persistSessionSelection();
      return this.loadState();
    }

    async refreshAccessToken() {
      if (this.refreshPromise) return this.refreshPromise;
      const self = this;
      this.refreshPromise = (async function () {
        try {
          const payload = await self.request('/auth/token/refresh/', {
            method: 'POST', auth: false, organization: false, retry: false,
            body: { refresh: self.refreshToken }
          });
          self.accessToken = payload.access;
          if (payload.refresh) self.refreshToken = payload.refresh;
          self.persistSessionSelection();
          return self.accessToken;
        } catch (error) {
          self.clearSession();
          throw error;
        } finally {
          self.refreshPromise = null;
        }
      })();
      return this.refreshPromise;
    }

    async restore() {
      if (!this.refreshToken) return null;
      await this.refreshAccessToken();
      await this.bootstrapIdentity();
      return this.loadState();
    }

    async bootstrapIdentity() {
      const payload = await this.request('/auth/me/', { organization: false });
      this.user = payload.user;
      this.memberships = payload.memberships || [];
      this.permissions = payload.permissions || [];
      this.emailVerificationEnabled = Boolean(payload.email_verification_enabled);
      if (!this.memberships.length) {
        this.organizationId = '';
        this.warehouseId = '';
        this.role = '';
        this.warehouses = [];
        this.persistSessionSelection();
        throw new ApiError('该账号尚未被主账号启用，请联系管理员。', 403, payload);
      }
      if (!this.memberships.some((item) => String(item.organization.id) === this.organizationId)) {
        this.organizationId = String(this.memberships[0].organization.id);
      }
      this.role = (this.memberships.find((item) => String(item.organization.id) === this.organizationId) || {}).role || '';
      await this.loadWarehouses();
      this.persistSessionSelection();
    }

    async loadWarehouses() {
      const warehouses = await this.listAll('/warehouses/');
      this.warehouses = warehouses.map(function (item) {
        const address = item.address && typeof item.address === 'object' ? (item.address.text || item.address.address || '') : (item.address || '');
        const contact = item.contact && typeof item.contact === 'object' ? (item.contact.name || item.contact.text || item.contact.phone || '') : (item.contact || '');
        return Object.assign({}, item, {
          type: item.warehouse_type || item.type || 'other', address: address, contact: contact,
          canReceive: item.can_receive !== false, canShip: item.can_ship !== false
        });
      });
      const active = this.warehouses.filter(function (item) { return item.active; });
      if (!active.length) throw new ApiError('当前组织没有可用仓库，请先在管理后台创建仓库。', 409, null);
      if (!active.some((item) => String(item.id) === this.warehouseId)) this.warehouseId = String(active[0].id);
    }

    async selectWarehouse(warehouseId) {
      if (!this.warehouses.some(function (item) { return String(item.id) === String(warehouseId) && item.active; })) {
        throw new ApiError('仓库不可用。', 404, null);
      }
      this.warehouseId = String(warehouseId);
      this.persistSessionSelection();
      return this.loadState();
    }

    async listAll(path) {
      const items = [];
      let next = path;
      let guard = 0;
      while (next && guard < 200) {
        const payload = await this.request(next);
        items.push.apply(items, pageItems(payload));
        next = payload && !Array.isArray(payload) ? payload.next : null;
        guard += 1;
      }
      if (guard >= 200) throw new ApiError('分页数据异常，已停止继续读取。', 500, null);
      return items;
    }

    async loadSyncVersion() {
      const payload = await this.request('/sync/version/');
      return Number(payload && payload.revision) || 0;
    }

    async pollForUpdates() {
      if (!this.accessToken || this.online === false) return null;
      const revision = await this.loadSyncVersion();
      if (this.syncRevision && revision !== this.syncRevision) return this.loadState();
      this.syncRevision = revision;
      return null;
    }

    canWrite() {
      return Boolean(this.user && (this.user.is_owner || this.permissions.some(function (item) { return item !== 'view'; })));
    }

    can(capability) {
      if (this.user && this.user.is_owner) return true;
      const key = CAPABILITY_KEYS[capability] || capability;
      return this.permissions.includes(key);
    }

    async listInternalAccounts() {
      return this.request('/internal-accounts/');
    }

    async createInternalAccount(payload) {
      return this.request('/internal-accounts/', { method: 'POST', body: payload });
    }

    async updateInternalAccount(id, payload) {
      return this.request('/internal-accounts/' + encodeURIComponent(id) + '/', { method: 'PATCH', body: payload });
    }

    async productSelectionStatus() {
      return this.request('/product-selection/status/');
    }

    async getAlphaShopConfig() { return this.request('/alphashop-config/'); }
    async saveAlphaShopConfig(payload) { return this.request('/alphashop-config/', { method: 'PUT', body: payload }); }

    async searchProductSelectionKeywords(payload) {
      return this.request('/product-selection/keywords/', { method: 'POST', body: payload });
    }

    async generateProductSelectionReport(payload) {
      return this.request('/product-selection/report/', { method: 'POST', body: payload });
    }

    async disableInternalAccount(id) {
      return this.request('/internal-accounts/' + encodeURIComponent(id) + '/', { method: 'DELETE' });
    }

    async requestOwnerPasswordChange() {
      return this.request('/auth/owner/password/change/request/', { method: 'POST', organization: false, body: {} });
    }

    async listTikTokConnections() { return this.listAll('/tiktok-shop-connections/'); }
    async startTikTokAuthorization(region) {
      return this.request('/tiktok-shop-connections/authorize/', { method: 'POST', body: { region: region || 'MY' } });
    }
    async refreshTikTokConnection(id) { return this.request('/tiktok-shop-connections/' + id + '/refresh/', { method: 'POST', body: {} }); }
    async disconnectTikTokConnection(id) { return this.request('/tiktok-shop-connections/' + id + '/disconnect/', { method: 'POST', body: {} }); }

    async listAIProviders() { return this.listAll('/ai-providers/'); }
    async saveAIProvider(payload) { return this.request('/ai-providers/', { method: 'POST', body: payload }); }
    async testAIProvider(id) { return this.request('/ai-providers/' + id + '/test/', { method: 'POST', body: {} }); }

    async confirmOwnerPasswordChange(challengeId, code, password) {
      return this.request('/auth/owner/password/change/confirm/', {
        method: 'POST', organization: false,
        body: { challenge_id: challengeId, code: code, password: password }
      });
    }

    idempotencyKey(scope, signature) {
      const slot = scope + ':' + String(signature || '');
      if (!this.pendingIdempotency.has(slot)) this.pendingIdempotency.set(slot, randomKey(scope));
      return { slot: slot, value: this.pendingIdempotency.get(slot) };
    }

    completeIdempotency(key, error) {
      if (!error || (error.status > 0 && error.status < 500)) this.pendingIdempotency.delete(key.slot);
    }

    async loadState() {
      const paths = [
        '/products/', '/suppliers/', '/purchase-orders/', '/stock-balances/', '/stock-ledger/',
        '/orders/', '/shipments/', '/returns/', '/competitors/', '/competitor-snapshots/',
        '/stock-transfers/', '/replenishment-policies/',
        '/replenishment/recommendations/?warehouse=' + encodeURIComponent(this.warehouseId)
      ];
      const values = await Promise.all(paths.map((path) => this.listAll(path)).concat([this.loadSyncVersion()]));
      const raw = {
        products: values[0], suppliers: values[1], purchaseOrders: values[2],
        balances: values[3], ledger: values[4], orders: values[5], shipments: values[6],
        returns: values[7], competitors: values[8], snapshots: values[9], transfers: values[10],
        replenishmentPolicies: values[11], replenishmentRecommendations: values[12]
      };
      this.cache = raw;
      this.syncRevision = values[13] || this.syncRevision;
      return this.adaptState(raw);
    }

    adaptState(raw) {
      const supplierById = new Map(raw.suppliers.map(function (item) { return [String(item.id), item]; }));
      const productBySku = new Map();
      const ownViewByApiProduct = new Map();
      const own = [];
      raw.products.forEach(function (item) {
        const skus = (item.skus || []).length ? item.skus : [null];
        const image = (item.images || [])[0] || null;
        const supplier = item.default_supplier ? supplierById.get(String(item.default_supplier)) : null;
        skus.forEach(function (sku, index) {
          const viewId = skus.length > 1 && sku ? String(item.id) + ':' + String(sku.id) : String(item.id);
          const view = {
            id: viewId, apiProductId: String(item.id), catalogProductId: String(item.id), skuId: sku ? String(sku.id) : '',
            imageId: image ? String(image.id) : '', defaultSupplierId: supplier ? String(supplier.id) : '',
            skuCount: (item.skus || []).length, skuActive: sku ? sku.active !== false : false,
            name: item.name, sku: sku ? sku.code : '', seller: item.seller || '', kind: 'own',
            market: item.market || '', salesCurrency: item.sales_currency || (sku ? sku.currency : 'CNY'),
            costCurrency: sku ? sku.currency : 'CNY', standardCost: sku ? number(sku.cost) : 0,
            safetyStock: sku ? number(sku.safety_stock) : 0, defaultSupplier: supplier ? supplier.name : '',
            status: item.status, productUrl: item.source_url || '', purchaseUrl: item.purchase_url || '',
            image: image ? image.url : '', monitoringEnabled: Boolean(item.monitoring_enabled),
            needsReview: !item.source_url || !image || !sku || number(sku.cost) <= 0,
            createdAt: item.created_at, updatedAt: item.updated_at
          };
          own.push(view);
          if (sku) productBySku.set(String(sku.id), viewId);
          if (index === 0) ownViewByApiProduct.set(String(item.id), viewId);
        });
      });
      const linkedProfileByProduct = new Map();
      const competitors = [];
      raw.competitors.forEach(function (item) {
        if (item.linked_product) {
          linkedProfileByProduct.set(String(item.linked_product), item);
          return;
        }
        competitors.push({
          id: String(item.id), apiCompetitorId: String(item.id), name: item.name,
          sku: '', seller: item.seller || '', kind: item.kind || 'direct', market: item.market || '',
          salesCurrency: item.currency || 'CNY', costCurrency: item.currency || 'CNY',
          standardCost: 0, safetyStock: 0, defaultSupplier: '', status: item.active ? 'active' : 'inactive',
          productUrl: item.url, purchaseUrl: '', image: item.image_url || '', monitoringEnabled: true,
          needsReview: !item.url || !item.image_url, createdAt: item.created_at, updatedAt: item.updated_at
        });
      });
      own.forEach(function (item) {
        const profile = linkedProfileByProduct.get(item.apiProductId);
        if (profile) item.apiCompetitorId = String(profile.id);
      });
      const products = own.concat(competitors);
      const productById = new Map(products.map(function (item) { return [item.id, item]; }));
      const competitorTarget = new Map();
      raw.competitors.forEach(function (item) {
        competitorTarget.set(String(item.id), item.linked_product ? (ownViewByApiProduct.get(String(item.linked_product)) || String(item.linked_product)) : String(item.id));
      });
      const snapshots = raw.snapshots.map(function (item) {
        const rawExtra = item.raw || {};
        const productId = competitorTarget.get(String(item.product)) || String(item.product);
        const product = productById.get(productId);
        return {
          id: String(item.id), apiSnapshotId: String(item.id), productId: productId,
          at: item.captured_at, currency: product ? product.salesCurrency : 'CNY',
          price: item.price == null ? 0 : number(item.price), sold: item.sold_count == null ? 0 : number(item.sold_count),
          rating: item.rating == null ? null : number(item.rating), reviews: item.review_count == null ? 0 : number(item.review_count),
          lowReviews: number(rawExtra.low_reviews), shopRating: rawExtra.shop_rating == null ? null : number(rawExtra.shop_rating),
          createdAt: item.created_at
        };
      });
      const poStatus = { draft: 'draft', submitted: 'transit', partial: 'partial', received: 'completed', cancelled: 'cancelled' };
      const purchaseOrders = raw.purchaseOrders.filter((item) => String(item.warehouse) === this.warehouseId).map(function (item) {
        return {
          id: String(item.id), apiStatus: item.status, number: item.number,
          supplier: (supplierById.get(String(item.supplier)) || {}).name || '未命名供应商',
          supplierId: String(item.supplier), warehouseId: LOCAL_WAREHOUSE_ID,
          status: poStatus[item.status] || item.status, orderedAt: item.ordered_at,
          expectedAt: item.expected_at ? String(item.expected_at).slice(0, 10) : '',
          extraCost: number(item.extra_cost), note: item.notes || '', createdAt: item.created_at, updatedAt: item.updated_at,
          lines: (item.lines || []).map(function (line) {
            const productId = productBySku.get(String(line.sku)) || '';
            return {
              id: String(line.id), skuId: String(line.sku), productId: productId,
              orderedQty: number(line.quantity_ordered), receivedQty: number(line.quantity_received),
              cancelledQty: item.status === 'cancelled' ? Math.max(0, number(line.quantity_ordered) - number(line.quantity_received)) : 0,
              unitCost: number(line.unit_cost)
            };
          })
        };
      });
      const inventoryBalances = raw.balances.filter((item) => String(item.warehouse) === this.warehouseId).map(function (item) {
        return {
          apiBalanceId: String(item.id), warehouseId: LOCAL_WAREHOUSE_ID, productId: productBySku.get(String(item.sku)) || '',
          onHand: number(item.on_hand), reserved: number(item.reserved), inTransit: number(item.in_transit),
          updatedAt: item.updated_at
        };
      }).filter(function (item) { return item.productId; });
      const movementType = { receipt: 'receipt', adjustment: 'adjustment', manual_inbound: 'manual_inbound', manual_outbound: 'manual_outbound', reversal: 'reversal', reserve: 'reserve', release: 'release', shipment: 'outbound', return: 'return' };
      const inventoryMovements = raw.ledger.filter((item) => String(item.warehouse) === this.warehouseId).map(function (item) {
        return {
          id: String(item.id), apiLedgerId: String(item.id), isReversed: Boolean(item.is_reversed), reversalInfo: item.reversal_info || null,
          warehouseId: LOCAL_WAREHOUSE_ID, productId: productBySku.get(String(item.sku)) || '',
          type: movementType[item.event_type] || item.event_type, onHandDelta: number(item.on_hand_delta),
          reservedDelta: number(item.reserved_delta), afterOnHand: number(item.on_hand_after), afterReserved: number(item.reserved_after),
          sourceType: item.reference_type, sourceId: item.reference_id, sourceLineId: '',
          sourceNumber: item.reference_type + ' · ' + item.reference_id, occurredAt: item.occurred_at,
          note: item.reason || ''
        };
      }).filter(function (item) { return item.productId; });
      const shipmentByOrder = new Map();
      raw.shipments.forEach(function (item) { shipmentByOrder.set(String(item.order), item); });
      const orderStatus = { draft: 'shortage', ready: 'shortage', allocated: 'picking', picking: 'review', verified: 'ready', shipped: 'shipped', cancelled: 'cancelled' };
      const salesOrders = raw.orders.filter((item) => String(item.warehouse) === this.warehouseId).map(function (item) {
        const shipment = shipmentByOrder.get(String(item.id));
        return {
          id: String(item.id), apiStatus: item.status, number: item.number,
          platform: item.platform || (item.customer || {}).platform || '手工订单',
          store: item.store || (item.customer || {}).store || '', orderedAt: item.ordered_at || item.created_at,
          trackingNumber: shipment ? shipment.tracking_number || '' : '', note: item.notes || '',
          status: orderStatus[item.status] || item.status, createdAt: item.created_at, updatedAt: item.updated_at,
          lines: (item.lines || []).map(function (line) {
            return {
              id: String(line.id), skuId: String(line.sku), productId: productBySku.get(String(line.sku)) || '',
              quantity: number(line.quantity), reservedQty: number(line.quantity_reserved), shippedQty: number(line.quantity_shipped)
            };
          })
        };
      });
      const orderById = new Map(salesOrders.map(function (item) { return [item.id, item]; }));
      const returns = raw.returns.filter((item) => String(item.warehouse) === this.warehouseId).map(function (item) {
        const original = orderById.get(String(item.original_order));
        return {
          id: String(item.id), number: item.number, orderId: String(item.original_order || ''),
          warehouseId: LOCAL_WAREHOUSE_ID, status: item.status, returnedAt: item.received_at || item.created_at,
          note: item.reason || '',
          lines: (item.lines || []).map(function (line) {
            const orderLine = original && original.lines.find(function (entry) { return entry.skuId === String(line.sku); });
            return {
              id: String(line.id), orderLineId: orderLine ? orderLine.id : '', skuId: String(line.sku),
              productId: productBySku.get(String(line.sku)) || '', quantity: number(line.quantity_received),
              expectedQty: number(line.quantity_expected), condition: line.condition
            };
          })
        };
      });
      const stockTransfers = raw.transfers.map(function (item) {
        return {
          id: String(item.id), number: item.number,
          sourceWarehouseId: String(item.source_warehouse), destinationWarehouseId: String(item.destination_warehouse),
          status: item.status, note: item.notes || '', shippedAt: item.dispatched_at,
          receivedAt: item.received_at, createdAt: item.created_at, updatedAt: item.updated_at,
          lines: (item.lines || []).map(function (line) {
            return {
              id: String(line.id), skuId: String(line.sku), productId: productBySku.get(String(line.sku)) || '',
              quantity: number(line.quantity), receivedQty: item.status === 'received' ? number(line.quantity) : 0
            };
          })
        };
      });
      const replenishmentPolicies = raw.replenishmentPolicies.map(function (item) {
        return {
          id: String(item.id), warehouseId: String(item.warehouse), skuId: String(item.sku),
          productId: productBySku.get(String(item.sku)) || '', leadTimeOverride: item.lead_time_override,
          reviewCycleDays: number(item.review_cycle_days), targetDays: number(item.target_days),
          minOrderQty: number(item.min_order_qty), packSize: number(item.pack_size),
          safetyStockOverride: item.safety_stock_override
        };
      });
      return {
        version: 6, revision: Date.now(),
        warehouses: [{ id: LOCAL_WAREHOUSE_ID, apiWarehouseId: this.warehouseId, name: (this.warehouses.find((item) => String(item.id) === this.warehouseId) || {}).name || '当前仓', active: true }],
        products: products, snapshots: snapshots, purchaseOrders: purchaseOrders, receipts: [],
        inventoryBalances: inventoryBalances, inventoryMovements: inventoryMovements,
        salesOrders: salesOrders, reservations: [], shipments: raw.shipments, returns: returns,
        stockTransfers: stockTransfers, replenishmentPolicies: replenishmentPolicies,
        replenishmentRecommendations: raw.replenishmentRecommendations,
        legacyStockEvents: [], migrationIssues: [], selectedProductId: snapshots[0] ? snapshots[0].productId : '',
        ui: { module: 'products', warehouseTab: 'purchase', competitorTab: 'products', warehouseId: LOCAL_WAREHOUSE_ID }
      };
    }

    findRawProduct(product) {
      return (this.cache.products || []).find(function (item) { return String(item.id) === String(product.apiProductId || product.id); });
    }

    warehousePayload(warehouse, includeActive) {
      const payload = {
        code: String(warehouse.code || '').trim().toUpperCase(), name: String(warehouse.name || '').trim(),
        warehouse_type: warehouse.type || warehouse.warehouse_type || 'other', country: String(warehouse.country || 'CN').trim().toUpperCase(),
        address: warehouse.address ? { text: String(warehouse.address) } : {},
        timezone: warehouse.timezone || 'Asia/Shanghai', contact: warehouse.contact ? { text: String(warehouse.contact) } : {},
        can_receive: warehouse.canReceive !== false, can_ship: warehouse.canShip !== false
      };
      if (includeActive) payload.active = warehouse.active !== false;
      return payload;
    }

    async saveWarehouse(warehouse, warehouseId) {
      const path = warehouseId ? '/warehouses/' + warehouseId + '/' : '/warehouses/';
      const result = await this.request(path, { method: warehouseId ? 'PATCH' : 'POST', body: this.warehousePayload(warehouse, !warehouseId) });
      await this.loadWarehouses();
      if (!warehouseId) this.warehouseId = String(result.id);
      this.persistSessionSelection();
      return result;
    }

    async createWarehouse(warehouse) { return this.saveWarehouse(warehouse, ''); }
    async updateWarehouse(warehouse) { return this.saveWarehouse(warehouse, warehouse.id); }

    async setWarehouseActive(warehouse, active) {
      const result = await this.request('/warehouses/' + warehouse.id + '/', { method: 'PATCH', body: { active: Boolean(active) } });
      await this.loadWarehouses();
      this.persistSessionSelection();
      return result;
    }

    async archiveWarehouse(warehouse) { return this.setWarehouseActive(warehouse, false); }

    async ensureSupplier(name) {
      const trimmed = String(name || '').trim();
      if (!trimmed) return null;
      let supplier = (this.cache.suppliers || []).find(function (item) { return item.name.trim().toLowerCase() === trimmed.toLowerCase(); });
      if (supplier) return supplier;
      const code = 'SUP-' + Date.now().toString(36).toUpperCase();
      supplier = await this.request('/suppliers/', { method: 'POST', body: { code: code, name: trimmed, active: true } });
      this.cache.suppliers = (this.cache.suppliers || []).concat([supplier]);
      return supplier;
    }

    async validateLocalImport(source) {
      return this.request('/local-imports/validate/', {
        method: 'POST',
        body: { warehouse: this.warehouseId, source: source }
      });
    }

    async commitLocalImport(source, sourceHash) {
      const key = this.idempotencyKey('local-import', sourceHash || 'backup');
      try {
        const result = await this.request('/local-imports/commit/', {
          method: 'POST',
          body: {
            warehouse: this.warehouseId,
            source: source,
            idempotency_key: key.value
          }
        });
        this.completeIdempotency(key);
        return result;
      } catch (error) {
        this.completeIdempotency(key, error);
        throw error;
      }
    }

    async ensureMonitoringProfile(product) {
      const body = {
        linked_product: product.apiProductId || product.id,
        name: product.name, kind: 'direct', platform: 'own', market: product.market || '',
        url: product.productUrl, image_url: /^https:\/\//i.test(product.image || '') ? product.image : '', seller: product.seller || '',
        currency: product.salesCurrency || 'CNY', active: true
      };
      const raw = product.apiCompetitorId
        ? await this.request('/competitors/' + product.apiCompetitorId + '/', { method: 'PATCH', body: body })
        : await this.request('/competitors/', { method: 'POST', body: body });
      product.apiCompetitorId = String(raw.id);
      return product.apiCompetitorId;
    }

    async saveProduct(product, initialSnapshot) {
      if (product.kind !== 'own') {
        if (/^data:image\//i.test(product.image || '')) product.image = await this.uploadDataImage(product.image, product.name || 'competitor');
        const payload = {
          name: product.name, kind: product.kind, platform: 'tiktok_shop', market: product.market || '',
          url: product.productUrl, image_url: product.image, seller: product.seller || '',
          currency: product.salesCurrency || 'CNY', active: product.status === 'active'
        };
        const saved = product.apiCompetitorId
          ? await this.request('/competitors/' + product.apiCompetitorId + '/', { method: 'PATCH', body: payload })
          : await this.request('/competitors/', { method: 'POST', body: payload });
        product.apiCompetitorId = String(saved.id);
        if (initialSnapshot) await this.saveSnapshot(product, initialSnapshot);
        return saved;
      }
      const supplier = await this.ensureSupplier(product.defaultSupplier);
      const payload = {
        name: product.name, description: '', seller: product.seller || '', market: product.market || '',
        sales_currency: product.salesCurrency || 'CNY', monitoring_enabled: Boolean(product.monitoringEnabled),
        source_url: product.productUrl, purchase_url: product.purchaseUrl || '',
        default_supplier: supplier ? supplier.id : null
      };
      let raw = this.findRawProduct(product);
      if (raw) {
        raw = await this.request('/products/' + raw.id + '/', { method: 'PATCH', body: payload });
      } else {
        raw = await this.request('/products/', { method: 'POST', body: payload });
        product.apiProductId = String(raw.id);
      }
      const requestedSkus = Array.isArray(product.skus) ? product.skus : [{
        id: product.skuId, code: product.sku, cost: product.standardCost,
        safetyStock: product.safetyStock, attributes: {}
      }];
      const existingSkus = raw.skus || [];
      const requestedIds = new Set(requestedSkus.filter(function (sku) { return sku.id; }).map(function (sku) { return String(sku.id); }));
      const requestedCodes = new Set();
      for (const sku of requestedSkus) {
        const code = String(sku.code || '').trim();
        if (!code) continue;
        if (requestedCodes.has(code.toUpperCase())) throw new ApiError('同一商品内的 SKU 编码不能重复。', 400, null);
        requestedCodes.add(code.toUpperCase());
        const currentSku = existingSkus.find(function (item) { return String(item.id) === String(sku.id); }) || null;
        const skuPayload = {
          product: raw.id, code: code, barcode: '', cost: sku.cost,
          currency: product.costCurrency || product.salesCurrency || 'CNY', safety_stock: sku.safetyStock || 0,
          active: true, attributes: sku.attributes || {}
        };
        const savedSku = currentSku
          ? await this.request('/skus/' + currentSku.id + '/', { method: 'PATCH', body: skuPayload })
          : await this.request('/skus/', { method: 'POST', body: skuPayload });
        sku.id = String(savedSku.id);
        requestedIds.add(String(savedSku.id));
      }
      for (const existingSku of existingSkus) {
        if (!requestedIds.has(String(existingSku.id)) && existingSku.active !== false) {
          await this.request('/skus/' + existingSku.id + '/', { method: 'PATCH', body: { active: false } });
        }
      }
      product.skuId = requestedSkus[0] && requestedSkus[0].id ? String(requestedSkus[0].id) : '';
      const rawImage = (raw.images || []).find(function (item) { return String(item.id) === String(product.imageId); }) || (raw.images || [])[0];
      if (product.image) {
        const imagePayload = { product: raw.id, url: product.image, alt: product.name, position: 0 };
        const savedImage = rawImage
          ? await this.request('/product-images/' + rawImage.id + '/', { method: 'PATCH', body: imagePayload })
          : await this.request('/product-images/', { method: 'POST', body: imagePayload });
        product.imageId = String(savedImage.id);
      } else if (rawImage) {
        await this.request('/product-images/' + rawImage.id + '/', { method: 'DELETE' });
      }
      if (product.status === 'draft') {
        if (raw.status !== 'draft') throw new ApiError('团队版已启用商品不能退回草稿，可改为停用。', 409, null);
      } else if (product.status === 'active') {
        raw = await this.request('/products/' + raw.id + '/activate/', { method: 'POST', body: {} });
      } else if (product.status === 'inactive') {
        if (raw.status === 'draft') await this.request('/products/' + raw.id + '/activate/', { method: 'POST', body: {} });
        await this.request('/products/' + raw.id + '/deactivate/', { method: 'POST', body: {} });
      }
      if (product.monitoringEnabled) {
        await this.ensureMonitoringProfile(product);
        if (initialSnapshot) await this.saveSnapshot(product, initialSnapshot);
      } else if (product.apiCompetitorId) {
        await this.request('/competitors/' + product.apiCompetitorId + '/', { method: 'PATCH', body: { active: false } });
      }
      return raw;
    }

    async uploadDataImage(dataUrl, name) {
      const response = await root.fetch(dataUrl);
      if (!response.ok) throw new ApiError('无法读取本地图片，请重新选择图片。', response.status, null);
      const blob = await response.blob();
      const extension = blob.type === 'image/png' ? 'png' : (blob.type === 'image/webp' ? 'webp' : 'jpg');
      const file = new root.File([blob], String(name || 'image').replace(/[^a-z0-9_-]+/gi, '-') + '.' + extension, { type: blob.type || 'image/jpeg' });
      const body = new root.FormData();
      body.append('file', file);
      const saved = await this.request('/media-assets/', { method: 'POST', body: body });
      return saved.url;
    }

    async setProductActive(product, active) {
      if (product.kind === 'own') {
        return this.request('/products/' + (product.apiProductId || product.id) + '/' + (active ? 'activate' : 'deactivate') + '/', { method: 'POST', body: {} });
      }
      return this.request('/competitors/' + (product.apiCompetitorId || product.id) + '/', { method: 'PATCH', body: { active: active } });
    }

    async deleteProduct(product) {
      const path = product.kind === 'own'
        ? '/products/' + (product.apiProductId || product.id) + '/'
        : '/competitors/' + (product.apiCompetitorId || product.id) + '/';
      return this.request(path, { method: 'DELETE' });
    }

    async createPurchase(order) {
      const supplier = await this.ensureSupplier(order.supplier);
      const payload = {
        number: order.number, supplier: supplier ? supplier.id : null, warehouse: this.warehouseId || null,
        currency: (order.lines[0] && order.lines[0].currency) || 'CNY', extra_cost: order.extraCost || 0,
        ordered_at: iso(order.orderedAt), expected_at: iso(order.expectedAt), notes: order.note || '',
        lines: order.lines.map(function (line) {
          return { sku: line.skuId, quantity_ordered: line.quantity, unit_cost: line.unitCost };
        })
      };
      const saved = await this.request('/purchase-orders/', { method: 'POST', body: payload });
      if (order.status !== 'draft' && order.lines.length) return this.request('/purchase-orders/' + saved.id + '/submit/', { method: 'POST', body: {} });
      return saved;
    }

    async submitPurchase(order) {
      return this.request('/purchase-orders/' + order.id + '/submit/', { method: 'POST', body: {} });
    }

    async cancelPurchase(order) {
      return this.request('/purchase-orders/' + order.id + '/cancel/', { method: 'POST', body: {} });
    }

    async deletePurchase(order) {
      return this.request('/purchase-orders/' + order.id + '/', { method: 'DELETE' });
    }

    async receivePurchase(order, lines) {
      const normalizedLines = (lines || []).map(function (line) {
        return { purchase_line: line.id, quantity: number(line.quantity), unit_cost: line.unitCost };
      }).filter(function (line) { return line.quantity > 0; });
      if (!normalizedLines.length) throw new ApiError('请至少填写一个商品的本次收货数量。', 400, null);
      const key = this.idempotencyKey('receipt', [order.id].concat(normalizedLines.map(function (line) { return line.purchase_line + ':' + line.quantity; }).sort()).join(':'));
      try {
        const result = await this.request('/receipts/', {
          method: 'POST',
          body: {
            purchase_order: order.id,
            number: 'GRN-' + key.value.slice(-24),
            idempotency_key: key.value,
            lines: normalizedLines
          }
        });
        this.completeIdempotency(key);
        return result;
      } catch (error) {
        this.completeIdempotency(key, error);
        throw error;
      }
    }

    async adjustInventory(product, operation, quantity, note) {
      const movementPath = operation === 'manual_inbound' ? '/stock-balances/manual-inbound/' : (operation === 'manual_outbound' ? '/stock-balances/manual-outbound/' : '');
      const subtract = operation === 'adjust_sub' || operation === 'damage';
      const key = this.idempotencyKey('adjustment', [this.warehouseId, product.skuId, operation, quantity, note].join(':'));
      try {
        const result = await this.request(movementPath || '/stock-balances/adjust/', {
          method: 'POST',
          body: movementPath ? {
            warehouse: this.warehouseId, sku: product.skuId, quantity: number(quantity), reason: note || '', idempotency_key: key.value
          } : {
            warehouse: this.warehouseId, sku: product.skuId,
            delta: (subtract ? -1 : 1) * number(quantity),
            reason: (operation + ' · ' + (note || '')).trim(),
            idempotency_key: key.value
          }
        });
        this.completeIdempotency(key);
        return result;
      } catch (error) {
        this.completeIdempotency(key, error);
        throw error;
      }
    }

    async deleteStockBalance(balance) {
      return this.request('/stock-balances/' + balance.apiBalanceId + '/', { method: 'DELETE' });
    }

    async revokeStockLedger(movement, reason) {
      return this.request('/stock-ledger/' + (movement.apiLedgerId || movement.id) + '/revoke/', {
        method: 'POST', body: { reason: reason || '' }
      });
    }

    async createAndShipTransfer(transfer) {
      const payload = {
        number: transfer.number, source_warehouse: transfer.sourceWarehouseId,
        destination_warehouse: transfer.destinationWarehouseId, notes: transfer.note || '',
        lines: transfer.lines.map(function (line) { return { sku: line.skuId, quantity: line.quantity }; })
      };
      const saved = await this.request('/stock-transfers/', { method: 'POST', body: payload });
      const key = this.idempotencyKey('transfer-dispatch', saved.id);
      try {
        const result = await this.request('/stock-transfers/' + saved.id + '/dispatch/', { method: 'POST', body: { idempotency_key: key.value } });
        this.completeIdempotency(key);
        return result;
      } catch (error) {
        this.completeIdempotency(key, error);
        error.createdTransfer = saved;
        throw error;
      }
    }

    async createTransfer(transfer) {
      return this.request('/stock-transfers/', {
        method: 'POST', body: {
          number: transfer.number, source_warehouse: transfer.sourceWarehouseId,
          destination_warehouse: transfer.destinationWarehouseId, notes: transfer.note || '',
          lines: transfer.lines.map(function (line) { return { sku: line.skuId, quantity: line.quantity }; })
        }
      });
    }

    async dispatchTransfer(transfer) {
      const key = this.idempotencyKey('transfer-dispatch', transfer.id);
      try {
        const result = await this.request('/stock-transfers/' + transfer.id + '/dispatch/', { method: 'POST', body: { idempotency_key: key.value } });
        this.completeIdempotency(key);
        return result;
      } catch (error) { this.completeIdempotency(key, error); throw error; }
    }

    async receiveTransfer(transfer) {
      const key = this.idempotencyKey('transfer-receive', transfer.id);
      try {
        const result = await this.request('/stock-transfers/' + transfer.id + '/receive/', { method: 'POST', body: { idempotency_key: key.value } });
        this.completeIdempotency(key);
        return result;
      } catch (error) { this.completeIdempotency(key, error); throw error; }
    }

    async cancelTransfer(transfer) {
      return this.request('/stock-transfers/' + transfer.id + '/cancel/', { method: 'POST', body: {} });
    }

    async createOrder(order) {
      const payload = {
        number: order.number, warehouse: this.warehouseId, platform: order.platform || '',
        store: order.store || '', ordered_at: iso(order.orderedAt), external_ref: '',
        customer: { platform: order.platform || '', store: order.store || '' }, notes: order.note || '',
        lines: order.lines.map(function (line) {
          return { sku: line.skuId, quantity: line.quantity, unit_price: 0 };
        })
      };
      const saved = await this.request('/orders/', { method: 'POST', body: payload });
      if (!order.lines.length) return { order: saved, shipped: false, draft: true };
      try {
        await this.confirmAndShipOrder({ id: saved.id, trackingNumber: order.trackingNumber || '' });
        return { order: saved, shipped: true };
      } catch (error) {
        if (error instanceof ApiError && [400, 409].includes(error.status)) return { order: saved, shipped: false, error: error.message };
        throw error;
      }
    }

    async confirmAndShipOrder(order) {
      const key = this.idempotencyKey('confirm-and-ship', [order.id, order.trackingNumber || ''].join(':'));
      try {
        const result = await this.request('/orders/' + order.id + '/confirm-and-ship/', {
          method: 'POST', body: {
            idempotency_key: key.value, number: 'SHP-' + key.value.slice(-24), tracking_number: order.trackingNumber || ''
          }
        });
        this.completeIdempotency(key);
        return result;
      } catch (error) { this.completeIdempotency(key, error); throw error; }
    }

    async allocateOrder(order) {
      const key = this.idempotencyKey('allocate', order.id);
      try {
        const result = await this.request('/orders/' + order.id + '/allocate/', { method: 'POST', body: { idempotency_key: key.value } });
        this.completeIdempotency(key);
        return result;
      } catch (error) {
        this.completeIdempotency(key, error);
        throw error;
      }
    }

    async advanceOrder(order) {
      if (order.apiStatus === 'allocated') return this.request('/orders/' + order.id + '/start-picking/', { method: 'POST', body: {} });
      if (order.apiStatus === 'picking') return this.request('/orders/' + order.id + '/verify/', { method: 'POST', body: {} });
      throw new ApiError('订单当前不能推进。', 409, null);
    }

    async shipOrder(order) {
      const key = this.idempotencyKey('shipment', [order.id, order.trackingNumber || ''].join(':'));
      try {
        const result = await this.request('/orders/' + order.id + '/ship/', {
          method: 'POST',
          body: {
            number: 'SHP-' + key.value.slice(-24), tracking_number: order.trackingNumber || '',
            idempotency_key: key.value
          }
        });
        this.completeIdempotency(key);
        return result;
      } catch (error) {
        this.completeIdempotency(key, error);
        throw error;
      }
    }

    async cancelOrder(order) {
      return this.request('/orders/' + order.id + '/cancel/', { method: 'POST', body: {} });
    }

    async receiveReturn(order, line, quantity, condition, note) {
      const key = this.idempotencyKey('return', [order.id, line.id, quantity, condition, note].join(':'));
      try {
        const result = await this.request('/returns/receive-from-order/', {
          method: 'POST',
          body: {
            idempotency_key: key.value,
            number: 'RTN-' + key.value.slice(-24), original_order: order.id, warehouse: this.warehouseId,
            reason: note || '',
            lines: [{ sku: line.skuId, quantity_expected: quantity, condition: condition || 'restock', unit_refund: 0 }]
          }
        });
        this.completeIdempotency(key);
        return result;
      } catch (error) {
        this.completeIdempotency(key, error);
        throw error;
      }
    }

    async saveSnapshot(product, snapshot) {
      let competitorId = product.apiCompetitorId || (product.kind === 'own' ? '' : product.id);
      if (product.kind === 'own' && !competitorId) competitorId = await this.ensureMonitoringProfile(product);
      return this.request('/competitor-snapshots/', {
        method: 'POST',
        body: {
          product: competitorId, captured_at: snapshot.at, price: snapshot.price,
          sold_count: snapshot.sold, rating: snapshot.rating, review_count: snapshot.reviews,
          availability: '', raw: { low_reviews: snapshot.lowReviews, shop_rating: snapshot.shopRating }
        }
      });
    }

    async saveQuickSalesSnapshot(product, snapshot) {
      let competitorId = product.apiCompetitorId || (product.kind === 'own' ? '' : product.id);
      if (product.kind === 'own' && !competitorId) competitorId = await this.ensureMonitoringProfile(product);
      return this.request('/competitor-snapshots/quick-sales/', {
        method: 'POST', body: { product: competitorId, sold_count: snapshot.sold, captured_at: snapshot.at }
      });
    }

    async loadReplenishmentRecommendations() {
      return this.listAll('/replenishment/recommendations/?warehouse=' + encodeURIComponent(this.warehouseId));
    }

    async saveReplenishmentPolicy(product, policy) {
      const existing = (this.cache.replenishmentPolicies || []).find(function (item) {
        return String(item.warehouse) === String(this.warehouseId) && String(item.sku) === String(product.skuId);
      }, this);
      const payload = {
        warehouse: this.warehouseId, sku: product.skuId,
        lead_time_override: policy.leadTimeOverride, review_cycle_days: policy.reviewCycleDays,
        target_days: policy.targetDays, min_order_qty: policy.minOrderQty, pack_size: policy.packSize,
        safety_stock_override: policy.safetyStockOverride
      };
      return this.request(existing ? '/replenishment-policies/' + existing.id + '/' : '/replenishment-policies/', {
        method: existing ? 'PATCH' : 'POST', body: payload
      });
    }

    async deleteReplenishmentPolicy(product) {
      const existing = (this.cache.replenishmentPolicies || []).find(function (item) {
        return String(item.warehouse) === String(this.warehouseId) && String(item.sku) === String(product.skuId);
      }, this);
      if (!existing) return null;
      return this.request('/replenishment-policies/' + existing.id + '/', { method: 'DELETE' });
    }

    async deleteSnapshot(snapshot) {
      return this.request('/competitor-snapshots/' + (snapshot.apiSnapshotId || snapshot.id) + '/', { method: 'DELETE' });
    }
  }

  root.DongboTeam = { TeamGateway: TeamGateway, ApiError: ApiError, errorMessage: errorMessage };
})(window);
